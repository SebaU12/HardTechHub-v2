import os
import re
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from uuid import uuid4

try:
    import psycopg
    from psycopg.rows import dict_row
    from psycopg_pool import ConnectionPool
except ImportError:  # pragma: no cover - dependency guard for source-only checks
    psycopg = None

from app.errors import InventoryError
from app.repository import InventoryRepository


DATABASE_URL = os.getenv("INVENTORY_TEST_DATABASE_URL")


SCHEMA_SQL = """
CREATE TABLE inventory_stock (
    product_id BIGINT PRIMARY KEY,
    available_quantity INTEGER NOT NULL CHECK (available_quantity >= 0),
    reserved_quantity INTEGER NOT NULL DEFAULT 0 CHECK (reserved_quantity >= 0),
    minimum_quantity INTEGER NOT NULL DEFAULT 0 CHECK (minimum_quantity >= 0),
    version BIGINT NOT NULL DEFAULT 0 CHECK (version >= 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (reserved_quantity <= available_quantity)
);
CREATE TABLE inventory_reservations (
    id UUID PRIMARY KEY,
    idempotency_key VARCHAR(100) NOT NULL UNIQUE,
    request_hash CHAR(64) NOT NULL,
    user_id VARCHAR(80) NOT NULL,
    order_id BIGINT UNIQUE,
    status VARCHAR(20) NOT NULL CHECK (status IN ('ACTIVE','CONFIRMED','RELEASED','EXPIRED','CANCELLED')),
    expires_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE inventory_reservation_items (
    reservation_id UUID NOT NULL REFERENCES inventory_reservations(id),
    product_id BIGINT NOT NULL REFERENCES inventory_stock(product_id),
    quantity INTEGER NOT NULL CHECK (quantity > 0),
    PRIMARY KEY (reservation_id, product_id)
);
CREATE TABLE stock_movements (
    id BIGSERIAL PRIMARY KEY,
    product_id BIGINT NOT NULL REFERENCES inventory_stock(product_id),
    movement_type VARCHAR(30) NOT NULL,
    quantity INTEGER NOT NULL,
    quantity_before INTEGER NOT NULL,
    quantity_after INTEGER NOT NULL,
    reservation_id UUID REFERENCES inventory_reservations(id),
    order_id BIGINT,
    reason TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""


class PoolDatabase:
    def __init__(self, pool):
        self.pool = pool

    @contextmanager
    def connection(self):
        with self.pool.connection() as conn:
            yield conn


@unittest.skipUnless(DATABASE_URL and psycopg, "set INVENTORY_TEST_DATABASE_URL to run")
class RepositoryIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.schema = f"inventory_test_{uuid4().hex}"
        if not re.fullmatch(r"inventory_test_[0-9a-f]+", cls.schema):
            raise RuntimeError("Unsafe test schema name")
        with psycopg.connect(DATABASE_URL, autocommit=True) as conn:
            conn.execute(f'CREATE SCHEMA "{cls.schema}"')
            conn.execute(f'SET search_path TO "{cls.schema}"')
            conn.execute(SCHEMA_SQL)
        cls.pool = ConnectionPool(
            DATABASE_URL,
            min_size=1,
            max_size=4,
            kwargs={"row_factory": dict_row, "options": f"-c search_path={cls.schema}"},
        )
        cls.repository = InventoryRepository(PoolDatabase(cls.pool))

    @classmethod
    def tearDownClass(cls):
        cls.pool.close()
        with psycopg.connect(DATABASE_URL, autocommit=True) as conn:
            conn.execute(f'DROP SCHEMA "{cls.schema}" CASCADE')

    def setUp(self):
        with self.pool.connection() as conn:
            conn.execute(
                "TRUNCATE stock_movements, inventory_reservation_items, "
                "inventory_reservations, inventory_stock RESTART IDENTITY CASCADE"
            )
        self.repository.adjust_stock(1, 5, 1, "seed")
        self.repository.adjust_stock(2, 2, 1, "seed")

    def test_multi_product_shortage_rolls_back_all_reserved_quantities(self):
        with self.assertRaises(InventoryError) as raised:
            self.repository.create_reservation(
                "key-shortage-0000000001",
                "usr-1",
                [{"product_id": 1, "quantity": 2}, {"product_id": 2, "quantity": 3}],
            )
        self.assertEqual(raised.exception.code, "INSUFFICIENT_STOCK")
        self.assertEqual(self.repository.get_stock(1)["reserved_quantity"], 0)
        self.assertEqual(self.repository.get_stock(2)["reserved_quantity"], 0)

    def test_reserve_confirm_and_cancel_are_idempotent(self):
        key = "key-confirm-00000000001"
        items = [{"product_id": 1, "quantity": 2}]
        reservation, created = self.repository.create_reservation(key, "usr-1", items)
        replay, replay_created = self.repository.create_reservation(key, "usr-1", items)
        self.assertTrue(created)
        self.assertFalse(replay_created)
        self.assertEqual(reservation["reservation_id"], replay["reservation_id"])
        self.assertEqual(self.repository.get_stock(1)["reserved_quantity"], 2)

        confirmed = self.repository.confirm_reservation(reservation["reservation_id"], 101)
        self.repository.confirm_reservation(reservation["reservation_id"], 101)
        self.assertEqual(confirmed["status"], "CONFIRMED")
        self.assertEqual(self.repository.get_stock(1)["available_quantity"], 3)

        cancelled = self.repository.cancel_reservation(
            reservation["reservation_id"], 101, "customer cancelled"
        )
        self.repository.cancel_reservation(
            reservation["reservation_id"], 101, "customer cancelled"
        )
        self.assertEqual(cancelled["status"], "CANCELLED")
        self.assertEqual(self.repository.get_stock(1)["available_quantity"], 5)

    def test_release_and_expiration_restore_sellable_stock(self):
        first, _ = self.repository.create_reservation(
            "key-release-00000000001", "usr-1", [{"product_id": 1, "quantity": 1}]
        )
        self.repository.release_reservation(first["reservation_id"])
        self.repository.release_reservation(first["reservation_id"])
        self.assertEqual(self.repository.get_stock(1)["reserved_quantity"], 0)

        second, _ = self.repository.create_reservation(
            "key-expire-00000000001", "usr-1", [{"product_id": 1, "quantity": 2}]
        )
        with self.pool.connection() as conn:
            conn.execute(
                "UPDATE inventory_reservations SET expires_at = %s WHERE id = %s",
                (datetime.now(timezone.utc) - timedelta(seconds=1), second["reservation_id"]),
            )
        expired = self.repository.expire_reservations()
        self.assertIn(second["reservation_id"], expired)
        self.assertEqual(self.repository.get_stock(1)["reserved_quantity"], 0)

    def test_concurrent_reservations_cannot_oversell(self):
        def reserve(key):
            try:
                self.repository.create_reservation(
                    key, "usr-concurrent", [{"product_id": 1, "quantity": 4}]
                )
                return "created"
            except InventoryError as exc:
                return exc.code

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(
                executor.map(
                    reserve,
                    ["key-concurrent-0000001", "key-concurrent-0000002"],
                )
            )
        self.assertCountEqual(results, ["created", "INSUFFICIENT_STOCK"])
        stock = self.repository.get_stock(1)
        self.assertEqual(stock["reserved_quantity"], 4)
        self.assertEqual(stock["sellable_quantity"], 1)


if __name__ == "__main__":
    unittest.main()
