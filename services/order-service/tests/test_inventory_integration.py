from __future__ import annotations

import os
import threading
import unittest
from copy import deepcopy
from unittest.mock import patch
from uuid import uuid4

import pymysql
from fastapi import HTTPException, Response

from app import main
from app.inventory_client import InventoryClientError, InventoryUnavailable


@unittest.skipUnless(
    os.getenv("ORDER_INTEGRATION_TEST") == "1",
    "set ORDER_INTEGRATION_TEST=1 to run MySQL integration tests",
)
class OrderInventoryIntegrationTests(unittest.TestCase):
    def setUp(self):
        self._clean_database()
        self.inventory = FakeInventory({1: 1, 2: 5})
        self.events = []
        self.patches = [
            patch.object(main, "inventory_client", self.inventory),
            patch.object(main, "fetch_product_snapshot", self._product),
            patch.object(main, "publish_order_created_event", self._publish_created),
            patch.object(main, "publish_order_status_changed_event", return_value="status.json"),
        ]
        for active_patch in self.patches:
            active_patch.start()

    def tearDown(self):
        for active_patch in reversed(self.patches):
            active_patch.stop()

    @staticmethod
    def _connection():
        return pymysql.connect(
            host=os.getenv("MYSQL_HOST", "mysql"),
            port=int(os.getenv("MYSQL_PORT", "3306")),
            user=os.getenv("MYSQL_USER", "hardtech"),
            password=os.getenv("MYSQL_PASSWORD", "hardtech"),
            database=os.getenv("MYSQL_DATABASE", "hardtech_orders"),
            cursorclass=pymysql.cursors.DictCursor,
            autocommit=True,
        )

    def _clean_database(self):
        conn = self._connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute("DELETE FROM order_items")
                cursor.execute("DELETE FROM orders")
        finally:
            conn.close()

    @staticmethod
    def _product(product_id):
        return {
            "id": product_id,
            "sku": f"SKU-{product_id}",
            "name": f"Product {product_id}",
            "price": "100.00",
        }

    def _publish_created(self, order_id, user_id, total_amount, items):
        key = f"raw/events/orders/order_{order_id}.json"
        self.events.append(key)
        return key

    @staticmethod
    def _payload(quantity=1):
        return main.CreateOrderRequest(
            user_id="usr_test",
            items=[main.OrderItemRequest(product_id=1, quantity=quantity)],
        )

    def _create(self, key, payload=None):
        response = Response()
        result = main.create_order(response, payload or self._payload(), key)
        return response, result

    def _rows(self):
        conn = self._connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute("SELECT * FROM orders ORDER BY id")
                return list(cursor.fetchall())
        finally:
            conn.close()

    def test_insufficient_stock_returns_409_without_order(self):
        with self.assertRaises(HTTPException) as raised:
            self._create("insufficient-key-0001", self._payload(quantity=2))

        self.assertEqual(raised.exception.status_code, 409)
        self.assertEqual(raised.exception.detail["code"], "INSUFFICIENT_STOCK")
        self.assertEqual(self._rows(), [])
        self.assertEqual(self.inventory.stock[1], 1)

    def test_same_key_replays_one_order_one_confirmation_and_one_event(self):
        first_response, first = self._create("replay-order-key-0001")
        second_response, second = self._create("replay-order-key-0001")

        self.assertEqual(first_response.status_code, 201)
        self.assertEqual(second_response.status_code, 200)
        self.assertEqual(first["order_id"], second["order_id"])
        self.assertEqual(len(self._rows()), 1)
        self.assertEqual(self.inventory.confirmed_changes, 1)
        self.assertEqual(self.inventory.stock[1], 0)
        self.assertEqual(len(self.events), 1)

    def test_same_key_with_other_payload_is_rejected(self):
        self._create("payload-conflict-0001")

        with self.assertRaises(HTTPException) as raised:
            self._create("payload-conflict-0001", self._payload(quantity=2))

        self.assertEqual(raised.exception.status_code, 409)
        self.assertEqual(raised.exception.detail["code"], "IDEMPOTENCY_KEY_REUSED")
        self.assertEqual(len(self._rows()), 1)

    def test_uncertain_confirmation_recovers_on_same_key_without_duplicate(self):
        self.inventory.confirm_unavailable = 1
        self.inventory.get_unavailable = 1
        key = "confirmation-retry-0001"

        with self.assertRaises(HTTPException) as raised:
            self._create(key)

        self.assertEqual(raised.exception.status_code, 503)
        self.assertEqual(self._rows()[0]["inventory_status"], "CONFIRMATION_PENDING")
        _, replay = self._create(key)
        self.assertEqual(replay["inventory_status"], "CONFIRMED")
        self.assertEqual(len(self._rows()), 1)
        self.assertEqual(self.inventory.confirmed_changes, 1)
        self.assertEqual(self.inventory.stock[1], 0)

    def test_mysql_failure_releases_reservation(self):
        with patch.object(
            main,
            "fetch_product_snapshot",
            return_value={"sku": "SKU", "name": "x" * 500, "price": "100.00"},
        ):
            with self.assertRaises(HTTPException) as raised:
                self._create("mysql-failure-key-0001")

        self.assertEqual(raised.exception.status_code, 500)
        self.assertEqual(self._rows(), [])
        reservation = next(iter(self.inventory.reservations.values()))
        self.assertEqual(reservation["status"], "RELEASED")
        self.assertEqual(self.inventory.stock[1], 1)

    def test_cancelling_confirmed_order_restores_stock_once(self):
        _, created = self._create("cancel-order-key-0001")
        self.assertEqual(self.inventory.stock[1], 0)

        result = main.update_order_status(
            created["order_id"], main.UpdateStatusRequest(status="CANCELLED")
        )
        repeated = main.update_order_status(
            created["order_id"], main.UpdateStatusRequest(status="CANCELLED")
        )

        self.assertEqual(result["inventory_status"], "CANCELLED")
        self.assertEqual(repeated["status"], "CANCELLED")
        self.assertEqual(self.inventory.stock[1], 1)
        self.assertEqual(self.inventory.cancelled_changes, 1)

    def test_two_buyers_cannot_sell_the_same_last_unit(self):
        barrier = threading.Barrier(2)
        outcomes = []

        def buy(key):
            barrier.wait()
            try:
                _, result = self._create(key)
                outcomes.append(("ok", result["order_id"]))
            except HTTPException as exc:
                outcomes.append(("error", exc.status_code))

        threads = [
            threading.Thread(target=buy, args=("buyer-one-key-00001",)),
            threading.Thread(target=buy, args=("buyer-two-key-00002",)),
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10)

        self.assertEqual(sorted(kind for kind, _ in outcomes), ["error", "ok"])
        self.assertIn(("error", 409), outcomes)
        self.assertEqual(len(self._rows()), 1)
        self.assertEqual(self.inventory.stock[1], 0)


class FakeInventory:
    def __init__(self, stock):
        self.stock = dict(stock)
        self.reserved = {product_id: 0 for product_id in stock}
        self.reservations = {}
        self.by_key = {}
        self.lock = threading.Lock()
        self.confirm_unavailable = 0
        self.get_unavailable = 0
        self.confirmed_changes = 0
        self.cancelled_changes = 0

    def reserve(self, idempotency_key, user_id, items):
        with self.lock:
            if idempotency_key in self.by_key:
                return deepcopy(self.reservations[self.by_key[idempotency_key]])
            insufficient = []
            for item in items:
                product_id = item["product_id"]
                sellable = self.stock.get(product_id, 0) - self.reserved.get(product_id, 0)
                if sellable < item["quantity"]:
                    insufficient.append(
                        {
                            "product_id": product_id,
                            "requested": item["quantity"],
                            "available": sellable,
                        }
                    )
            if insufficient:
                raise InventoryClientError(
                    409,
                    {
                        "code": "INSUFFICIENT_STOCK",
                        "message": "There is not enough stock",
                        "items": insufficient,
                    },
                )
            reservation_id = str(uuid4())
            reservation = {
                "reservation_id": reservation_id,
                "status": "ACTIVE",
                "user_id": user_id,
                "order_id": None,
                "items": deepcopy(items),
            }
            for item in items:
                self.reserved[item["product_id"]] += item["quantity"]
            self.by_key[idempotency_key] = reservation_id
            self.reservations[reservation_id] = reservation
            return deepcopy(reservation)

    def get_reservation(self, reservation_id):
        with self.lock:
            if self.get_unavailable:
                self.get_unavailable -= 1
                raise InventoryUnavailable()
            return deepcopy(self.reservations[reservation_id])

    def confirm(self, reservation_id, order_id):
        with self.lock:
            if self.confirm_unavailable:
                self.confirm_unavailable -= 1
                raise InventoryUnavailable()
            reservation = self.reservations[reservation_id]
            if reservation["status"] == "CONFIRMED":
                if reservation["order_id"] != order_id:
                    raise InventoryClientError(409, {"code": "RESERVATION_ORDER_CONFLICT"})
                return deepcopy(reservation)
            if reservation["status"] != "ACTIVE":
                raise InventoryClientError(409, {"code": "RESERVATION_NOT_ACTIVE"})
            for item in reservation["items"]:
                product_id = item["product_id"]
                self.stock[product_id] -= item["quantity"]
                self.reserved[product_id] -= item["quantity"]
            reservation["status"] = "CONFIRMED"
            reservation["order_id"] = order_id
            self.confirmed_changes += 1
            return deepcopy(reservation)

    def release(self, reservation_id):
        with self.lock:
            reservation = self.reservations[reservation_id]
            if reservation["status"] == "ACTIVE":
                for item in reservation["items"]:
                    self.reserved[item["product_id"]] -= item["quantity"]
                reservation["status"] = "RELEASED"
            return deepcopy(reservation)

    def cancel(self, reservation_id, order_id, _reason):
        with self.lock:
            reservation = self.reservations[reservation_id]
            if reservation["status"] == "CANCELLED":
                return deepcopy(reservation)
            if reservation["status"] != "CONFIRMED" or reservation["order_id"] != order_id:
                raise InventoryClientError(409, {"code": "RESERVATION_NOT_CANCELLABLE"})
            for item in reservation["items"]:
                self.stock[item["product_id"]] += item["quantity"]
            reservation["status"] = "CANCELLED"
            self.cancelled_changes += 1
            return deepcopy(reservation)


if __name__ == "__main__":
    unittest.main()
