from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable
from uuid import UUID, uuid4

from app.errors import InventoryError, conflict, not_found


def normalize_items(items: Iterable[Any]) -> list[dict[str, int]]:
    consolidated: dict[int, int] = {}
    for item in items:
        product_id = int(item.product_id if hasattr(item, "product_id") else item["product_id"])
        quantity = int(item.quantity if hasattr(item, "quantity") else item["quantity"])
        consolidated[product_id] = consolidated.get(product_id, 0) + quantity
        if consolidated[product_id] > 1000:
            raise InventoryError(
                422,
                "INVALID_RESERVATION_QUANTITY",
                "The consolidated quantity for a product cannot exceed 1000",
                product_id=product_id,
            )
    return [
        {"product_id": product_id, "quantity": consolidated[product_id]}
        for product_id in sorted(consolidated)
    ]


def reservation_request_hash(user_id: str, items: list[dict[str, int]]) -> str:
    canonical = json.dumps(
        {"user_id": user_id, "items": items},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _stock_response(row: dict[str, Any]) -> dict[str, Any]:
    sellable = row["available_quantity"] - row["reserved_quantity"]
    return {
        "product_id": row["product_id"],
        "available_quantity": row["available_quantity"],
        "reserved_quantity": row["reserved_quantity"],
        "sellable_quantity": sellable,
        "minimum_quantity": row["minimum_quantity"],
        "low_stock": sellable <= row["minimum_quantity"],
        "updated_at": row["updated_at"],
    }


class InventoryRepository:
    def __init__(self, db: Any) -> None:
        self.db = db

    def get_stock(self, product_id: int) -> dict[str, Any]:
        with self.db.connection() as conn, conn.cursor() as cursor:
            cursor.execute("SELECT * FROM inventory_stock WHERE product_id = %s", (product_id,))
            row = cursor.fetchone()
        if row is None:
            raise not_found("INVENTORY_NOT_FOUND", "Inventory was not initialized", product_id=product_id)
        return _stock_response(row)

    def stock_exists(self, product_id: int) -> bool:
        with self.db.connection() as conn, conn.cursor() as cursor:
            cursor.execute("SELECT 1 FROM inventory_stock WHERE product_id = %s", (product_id,))
            return cursor.fetchone() is not None

    def list_low_stock(self, limit: int, offset: int) -> list[dict[str, Any]]:
        with self.db.connection() as conn, conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT * FROM inventory_stock
                WHERE available_quantity - reserved_quantity <= minimum_quantity
                ORDER BY product_id
                LIMIT %s OFFSET %s
                """,
                (limit, offset),
            )
            return [_stock_response(row) for row in cursor.fetchall()]

    def adjust_stock(
        self,
        product_id: int,
        quantity_delta: int,
        minimum_quantity: int | None,
        reason: str,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        with self.db.connection() as conn, conn.transaction(), conn.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_xact_lock(%s)", (product_id,))
            cursor.execute(
                "SELECT * FROM inventory_stock WHERE product_id = %s FOR UPDATE",
                (product_id,),
            )
            row = cursor.fetchone()
            if row is None:
                movement_type = "INITIAL_STOCK"
                if quantity_delta < 0:
                    raise InventoryError(
                        400,
                        "INVALID_ADJUSTMENT",
                        "Initial stock cannot be negative",
                        product_id=product_id,
                    )
                before = 0
                before_low_stock = False
                after = quantity_delta
                minimum = minimum_quantity if minimum_quantity is not None else 0
                cursor.execute(
                    """
                    INSERT INTO inventory_stock
                        (product_id, available_quantity, reserved_quantity, minimum_quantity, version)
                    VALUES (%s, %s, 0, %s, 1)
                    RETURNING *
                    """,
                    (product_id, after, minimum),
                )
            else:
                movement_type = "MANUAL_ADJUSTMENT"
                before = row["available_quantity"]
                before_low_stock = (
                    before - row["reserved_quantity"] <= row["minimum_quantity"]
                )
                after = before + quantity_delta
                if after < 0:
                    raise InventoryError(
                        400,
                        "INVALID_ADJUSTMENT",
                        "Adjustment would make physical stock negative",
                        product_id=product_id,
                    )
                if after < row["reserved_quantity"]:
                    raise conflict(
                        "RESERVED_STOCK_CONFLICT",
                        "Adjustment would leave less physical stock than reserved stock",
                        product_id=product_id,
                        reserved_quantity=row["reserved_quantity"],
                    )
                minimum = row["minimum_quantity"] if minimum_quantity is None else minimum_quantity
                cursor.execute(
                    """
                    UPDATE inventory_stock
                    SET available_quantity = %s, minimum_quantity = %s,
                        version = version + 1, updated_at = now()
                    WHERE product_id = %s
                    RETURNING *
                    """,
                    (after, minimum, product_id),
                )
            updated = cursor.fetchone()
            cursor.execute(
                """
                INSERT INTO stock_movements
                    (product_id, movement_type, quantity, quantity_before, quantity_after, reason)
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (product_id, movement_type, quantity_delta, before, after, reason),
            )
        stock = _stock_response(updated)
        event_context = {
            "quantity_delta": quantity_delta,
            "quantity_before": before,
            "quantity_after": after,
            "reason": reason,
            "became_low_stock": (
                stock["low_stock"] and not before_low_stock
            ),
        }
        return stock, event_context

    def create_reservation(
        self,
        idempotency_key: str,
        user_id: str,
        items: list[dict[str, int]],
    ) -> tuple[dict[str, Any], bool, list[dict[str, Any]]]:
        request_hash = reservation_request_hash(user_id, items)
        reservation_id = uuid4()
        expires_at = datetime.now(timezone.utc) + timedelta(
            seconds=int(os.getenv("RESERVATION_TTL_SECONDS", "600"))
        )
        with self.db.connection() as conn, conn.transaction(), conn.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (idempotency_key,))
            cursor.execute(
                "SELECT * FROM inventory_reservations WHERE idempotency_key = %s FOR UPDATE",
                (idempotency_key,),
            )
            existing = cursor.fetchone()
            if existing is not None:
                if existing["request_hash"] != request_hash:
                    raise conflict(
                        "IDEMPOTENCY_KEY_REUSED",
                        "Idempotency key was already used with a different request",
                    )
                return self._reservation_with_items(cursor, existing), False, []

            product_ids = [item["product_id"] for item in items]
            cursor.execute(
                """
                SELECT * FROM inventory_stock
                WHERE product_id = ANY(%s)
                ORDER BY product_id
                FOR UPDATE
                """,
                (product_ids,),
            )
            stocks = {row["product_id"]: row for row in cursor.fetchall()}
            missing = [product_id for product_id in product_ids if product_id not in stocks]
            if missing:
                raise not_found(
                    "INVENTORY_NOT_FOUND",
                    "Inventory was not initialized for one or more products",
                    product_ids=missing,
                )
            insufficient = []
            low_stock_products = []
            for item in items:
                stock = stocks[item["product_id"]]
                sellable = stock["available_quantity"] - stock["reserved_quantity"]
                if sellable < item["quantity"]:
                    insufficient.append(
                        {
                            "product_id": item["product_id"],
                            "requested": item["quantity"],
                            "available": sellable,
                        }
                    )
            if insufficient:
                raise conflict(
                    "INSUFFICIENT_STOCK",
                    "There is not enough stock for one or more products",
                    items=insufficient,
                )

            cursor.execute(
                """
                INSERT INTO inventory_reservations
                    (id, idempotency_key, request_hash, user_id, status, expires_at)
                VALUES (%s, %s, %s, %s, 'ACTIVE', %s)
                RETURNING *
                """,
                (reservation_id, idempotency_key, request_hash, user_id, expires_at),
            )
            reservation = cursor.fetchone()
            for item in items:
                stock = stocks[item["product_id"]]
                before_sellable = stock["available_quantity"] - stock["reserved_quantity"]
                cursor.execute(
                    """
                    INSERT INTO inventory_reservation_items (reservation_id, product_id, quantity)
                    VALUES (%s, %s, %s)
                    """,
                    (reservation_id, item["product_id"], item["quantity"]),
                )
                cursor.execute(
                    """
                    UPDATE inventory_stock
                    SET reserved_quantity = reserved_quantity + %s,
                        version = version + 1, updated_at = now()
                    WHERE product_id = %s
                    """,
                    (item["quantity"], item["product_id"]),
                )
                after_sellable = before_sellable - item["quantity"]
                if before_sellable > stock["minimum_quantity"] and after_sellable <= stock["minimum_quantity"]:
                    low_stock_products.append(
                        {
                            "product_id": item["product_id"],
                            "available_quantity": stock["available_quantity"],
                            "reserved_quantity": stock["reserved_quantity"] + item["quantity"],
                            "sellable_quantity": after_sellable,
                            "minimum_quantity": stock["minimum_quantity"],
                        }
                    )
        return self._format_reservation(reservation, items), True, low_stock_products

    def get_reservation(self, reservation_id: UUID) -> dict[str, Any]:
        with self.db.connection() as conn, conn.cursor() as cursor:
            cursor.execute("SELECT * FROM inventory_reservations WHERE id = %s", (reservation_id,))
            reservation = cursor.fetchone()
            if reservation is None:
                raise not_found("RESERVATION_NOT_FOUND", "Reservation was not found")
            return self._reservation_with_items(cursor, reservation)

    def confirm_reservation(self, reservation_id: UUID, order_id: int) -> tuple[dict[str, Any], bool]:
        with self.db.connection() as conn, conn.transaction(), conn.cursor() as cursor:
            reservation = self._locked_reservation(cursor, reservation_id)
            if reservation["status"] == "CONFIRMED":
                if reservation["order_id"] != order_id:
                    raise conflict(
                        "RESERVATION_ORDER_CONFLICT",
                        "Reservation is associated with another order",
                    )
                return self._reservation_with_items(cursor, reservation), False
            if reservation["status"] != "ACTIVE":
                raise conflict("RESERVATION_NOT_ACTIVE", "Reservation is not active")
            if reservation["expires_at"] <= datetime.now(timezone.utc):
                raise conflict("RESERVATION_NOT_ACTIVE", "Reservation has expired")

            cursor.execute("SELECT pg_advisory_xact_lock(%s)", (order_id,))
            cursor.execute(
                "SELECT id FROM inventory_reservations WHERE order_id = %s AND id <> %s",
                (order_id, reservation_id),
            )
            if cursor.fetchone() is not None:
                raise conflict(
                    "RESERVATION_ORDER_CONFLICT",
                    "Order is already associated with another reservation",
                )

            items = self._lock_items_and_stock(cursor, reservation_id)
            for item in items:
                cursor.execute(
                    "SELECT available_quantity FROM inventory_stock WHERE product_id = %s",
                    (item["product_id"],),
                )
                before = cursor.fetchone()["available_quantity"]
                after = before - item["quantity"]
                cursor.execute(
                    """
                    UPDATE inventory_stock
                    SET available_quantity = available_quantity - %s,
                        reserved_quantity = reserved_quantity - %s,
                        version = version + 1, updated_at = now()
                    WHERE product_id = %s
                    """,
                    (item["quantity"], item["quantity"], item["product_id"]),
                )
                cursor.execute(
                    """
                    INSERT INTO stock_movements
                        (product_id, movement_type, quantity, quantity_before, quantity_after,
                         reservation_id, order_id, reason)
                    VALUES (%s, 'SALE_CONFIRMED', %s, %s, %s, %s, %s, 'Order confirmed')
                    """,
                    (item["product_id"], -item["quantity"], before, after, reservation_id, order_id),
                )
            cursor.execute(
                """
                UPDATE inventory_reservations
                SET status = 'CONFIRMED', order_id = %s, updated_at = now()
                WHERE id = %s RETURNING *
                """,
                (order_id, reservation_id),
            )
            updated = cursor.fetchone()
        return self._format_reservation(updated, items), True

    def release_reservation(self, reservation_id: UUID) -> tuple[dict[str, Any], bool]:
        with self.db.connection() as conn, conn.transaction(), conn.cursor() as cursor:
            reservation = self._locked_reservation(cursor, reservation_id)
            if reservation["status"] == "RELEASED":
                return self._reservation_with_items(cursor, reservation), False
            if reservation["status"] == "CONFIRMED" or reservation["status"] == "CANCELLED":
                raise conflict(
                    "RESERVATION_ALREADY_CONFIRMED",
                    "A confirmed sale must be cancelled instead of released",
                )
            if reservation["status"] != "ACTIVE":
                raise conflict("RESERVATION_NOT_ACTIVE", "Reservation is not active")
            items = self._lock_items_and_stock(cursor, reservation_id)
            self._decrease_reserved(cursor, items)
            cursor.execute(
                """
                UPDATE inventory_reservations
                SET status = 'RELEASED', updated_at = now()
                WHERE id = %s RETURNING *
                """,
                (reservation_id,),
            )
            updated = cursor.fetchone()
        return self._format_reservation(updated, items), True

    def cancel_reservation(
        self, reservation_id: UUID, order_id: int, reason: str
    ) -> tuple[dict[str, Any], bool]:
        with self.db.connection() as conn, conn.transaction(), conn.cursor() as cursor:
            reservation = self._locked_reservation(cursor, reservation_id)
            if reservation["order_id"] is not None and reservation["order_id"] != order_id:
                raise conflict(
                    "RESERVATION_ORDER_CONFLICT",
                    "Reservation is associated with another order",
                )
            if reservation["status"] == "CANCELLED":
                return self._reservation_with_items(cursor, reservation), False
            if reservation["status"] != "CONFIRMED":
                raise conflict(
                    "RESERVATION_NOT_CONFIRMED",
                    "Only a confirmed reservation can be cancelled",
                )
            items = self._lock_items_and_stock(cursor, reservation_id)
            for item in items:
                cursor.execute(
                    "SELECT available_quantity FROM inventory_stock WHERE product_id = %s",
                    (item["product_id"],),
                )
                before = cursor.fetchone()["available_quantity"]
                after = before + item["quantity"]
                cursor.execute(
                    """
                    UPDATE inventory_stock
                    SET available_quantity = available_quantity + %s,
                        version = version + 1, updated_at = now()
                    WHERE product_id = %s
                    """,
                    (item["quantity"], item["product_id"]),
                )
                cursor.execute(
                    """
                    INSERT INTO stock_movements
                        (product_id, movement_type, quantity, quantity_before, quantity_after,
                         reservation_id, order_id, reason)
                    VALUES (%s, 'ORDER_CANCELLED', %s, %s, %s, %s, %s, %s)
                    """,
                    (item["product_id"], item["quantity"], before, after,
                     reservation_id, order_id, reason),
                )
            cursor.execute(
                """
                UPDATE inventory_reservations
                SET status = 'CANCELLED', updated_at = now()
                WHERE id = %s RETURNING *
                """,
                (reservation_id,),
            )
            updated = cursor.fetchone()
        return self._format_reservation(updated, items), True

    def expire_reservations(self, batch_size: int = 50) -> list[dict[str, Any]]:
        expired_reservations: list[dict[str, Any]] = []
        with self.db.connection() as conn, conn.transaction(), conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT * FROM inventory_reservations
                WHERE status = 'ACTIVE' AND expires_at <= now()
                ORDER BY expires_at
                FOR UPDATE SKIP LOCKED
                LIMIT %s
                """,
                (batch_size,),
            )
            reservations = cursor.fetchall()
            for reservation in reservations:
                reservation_id = reservation["id"]
                items = self._lock_items_and_stock(cursor, reservation_id)
                self._decrease_reserved(cursor, items)
                cursor.execute(
                    """
                    UPDATE inventory_reservations
                    SET status = 'EXPIRED', updated_at = now()
                    WHERE id = %s
                    """,
                    (reservation_id,),
                )
                expired_reservations.append(
                    {
                        "reservation": self._format_reservation(reservation, items)
                        | {"status": "EXPIRED"},
                        "user_id": reservation["user_id"],
                    }
                )
        return expired_reservations

    @staticmethod
    def _locked_reservation(cursor: Any, reservation_id: UUID) -> dict[str, Any]:
        cursor.execute(
            "SELECT * FROM inventory_reservations WHERE id = %s FOR UPDATE",
            (reservation_id,),
        )
        reservation = cursor.fetchone()
        if reservation is None:
            raise not_found("RESERVATION_NOT_FOUND", "Reservation was not found")
        return reservation

    @staticmethod
    def _lock_items_and_stock(cursor: Any, reservation_id: UUID) -> list[dict[str, int]]:
        cursor.execute(
            """
            SELECT product_id, quantity FROM inventory_reservation_items
            WHERE reservation_id = %s ORDER BY product_id
            """,
            (reservation_id,),
        )
        items = list(cursor.fetchall())
        product_ids = [item["product_id"] for item in items]
        cursor.execute(
            """
            SELECT product_id FROM inventory_stock
            WHERE product_id = ANY(%s) ORDER BY product_id FOR UPDATE
            """,
            (product_ids,),
        )
        cursor.fetchall()
        return items

    @staticmethod
    def _decrease_reserved(cursor: Any, items: list[dict[str, int]]) -> None:
        for item in items:
            cursor.execute(
                """
                UPDATE inventory_stock
                SET reserved_quantity = reserved_quantity - %s,
                    version = version + 1, updated_at = now()
                WHERE product_id = %s
                """,
                (item["quantity"], item["product_id"]),
            )

    @classmethod
    def _reservation_with_items(cls, cursor: Any, reservation: dict[str, Any]) -> dict[str, Any]:
        cursor.execute(
            """
            SELECT product_id, quantity FROM inventory_reservation_items
            WHERE reservation_id = %s ORDER BY product_id
            """,
            (reservation["id"],),
        )
        return cls._format_reservation(reservation, list(cursor.fetchall()))

    @staticmethod
    def _format_reservation(
        reservation: dict[str, Any], items: list[dict[str, int]]
    ) -> dict[str, Any]:
        return {
            "reservation_id": reservation["id"],
            "status": reservation["status"],
            "expires_at": reservation["expires_at"],
            "order_id": reservation["order_id"],
            "items": items,
            "_user_id": reservation["user_id"],
        }
