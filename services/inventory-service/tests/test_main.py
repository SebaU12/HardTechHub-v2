import os
import asyncio
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from uuid import uuid4

from fastapi import Response
from fastapi.exceptions import RequestValidationError
from pydantic import ValidationError

from app.errors import conflict
from app import main
from app.repository import normalize_items, reservation_request_hash


NOW = datetime.now(timezone.utc)


def reservation_payload(reservation_id=None):
    return {
        "reservation_id": reservation_id or uuid4(),
        "status": "ACTIVE",
        "expires_at": NOW + timedelta(minutes=10),
        "order_id": None,
        "items": [{"product_id": 1, "quantity": 3}],
        "_user_id": "usr_001",
    }


class Item:
    def __init__(self, product_id, quantity):
        self.product_id = product_id
        self.quantity = quantity


class InventoryUnitTests(unittest.TestCase):
    def test_normalizes_duplicate_items_in_stable_order(self):
        normalized = normalize_items([Item(9, 1), Item(2, 4), Item(9, 2)])
        self.assertEqual(
            normalized,
            [{"product_id": 2, "quantity": 4}, {"product_id": 9, "quantity": 3}],
        )

    def test_request_hash_is_stable_and_includes_user(self):
        items = [{"product_id": 1, "quantity": 2}]
        self.assertEqual(
            reservation_request_hash("user-a", items),
            reservation_request_hash("user-a", list(items)),
        )
        self.assertNotEqual(
            reservation_request_hash("user-a", items),
            reservation_request_hash("user-b", items),
        )

    def test_consolidated_quantity_is_limited(self):
        with self.assertRaises(Exception) as raised:
            normalize_items([Item(1, 600), Item(1, 500)])
        self.assertEqual(raised.exception.code, "INVALID_RESERVATION_QUANTITY")


class InventoryApiTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {"EXPIRATION_WORKER_ENABLED": "false"})
        self.env.start()

    def tearDown(self):
        self.env.stop()

    def test_health_is_lightweight(self):
        with patch.object(main.repository, "get_stock") as db_call:
            response = main.healthcheck()
        self.assertEqual(response["status"], "healthy")
        db_call.assert_not_called()

    def test_create_reservation_returns_201_then_200_for_replay(self):
        body = main.CreateReservationRequest(
            user_id="usr_001", items=[{"product_id": 1, "quantity": 3}]
        )
        key = "00000000-0000-4000-8000-000000000001"
        with patch.object(
            main.repository,
            "create_reservation",
            side_effect=[
                (reservation_payload(), True, []),
                (reservation_payload(), False, []),
            ],
        ), patch.object(main, "publish_events", return_value=(True, ["event-key"])) as publish:
            first_response = Response(status_code=201)
            replay_response = Response(status_code=201)
            main.create_reservation(first_response, body, key)
            main.create_reservation(replay_response, body, key)
        self.assertEqual(first_response.status_code, 201)
        self.assertEqual(replay_response.status_code, 200)
        publish.assert_called_once()

    def test_business_errors_use_uniform_contract(self):
        error = conflict(
            "INSUFFICIENT_STOCK",
            "There is not enough stock for one or more products",
            items=[{"product_id": 1, "requested": 3, "available": 1}],
        )
        response = asyncio.run(main.inventory_error_handler(None, error))
        self.assertEqual(response.status_code, 409)
        self.assertIn(b'"code":"INSUFFICIENT_STOCK"', response.body)
        self.assertIn(b'"available":1', response.body)

    def test_repository_business_error_propagates_to_handler(self):
        error = conflict("INSUFFICIENT_STOCK", "No stock", items=[])
        payload = main.CreateReservationRequest(
            user_id="usr_001", items=[{"product_id": 1, "quantity": 3}]
        )
        with patch.object(main.repository, "create_reservation", side_effect=error):
            with self.assertRaises(type(error)) as raised:
                main.create_reservation(
                    Response(status_code=201),
                    payload,
                    "00000000-0000-4000-8000-000000000001",
                )
        self.assertEqual(raised.exception.code, "INSUFFICIENT_STOCK")

    def test_new_stock_is_validated_against_catalog(self):
        stock = {
            "product_id": 7,
            "available_quantity": 10,
            "reserved_quantity": 0,
            "sellable_quantity": 10,
            "minimum_quantity": 2,
            "low_stock": False,
            "updated_at": NOW,
        }
        with patch.object(main.repository, "stock_exists", return_value=False), patch.object(
            main, "validate_catalog_product"
        ) as catalog, patch.object(
            main.repository,
            "adjust_stock",
            return_value=(
                stock,
                {
                    "quantity_delta": 10,
                    "quantity_before": 0,
                    "quantity_after": 10,
                    "reason": "Initial delivery",
                    "became_low_stock": False,
                },
            ),
        ), patch.object(main, "publish_events", return_value=(True, ["event-key"])):
            response = main.adjust_stock(
                main.AdjustmentRequest(
                    product_id=7,
                    quantity_delta=10,
                    minimum_quantity=2,
                    reason="Initial delivery",
                )
            )
        self.assertEqual(response["available_quantity"], 10)
        catalog.assert_called_once_with(7)

    def test_s3_failure_does_not_rollback_committed_adjustment(self):
        stock = {
            "product_id": 7,
            "available_quantity": 10,
            "reserved_quantity": 0,
            "sellable_quantity": 10,
            "minimum_quantity": 2,
            "low_stock": False,
            "updated_at": NOW,
        }
        context = {
            "quantity_delta": 10,
            "quantity_before": 0,
            "quantity_after": 10,
            "reason": "Initial delivery",
            "became_low_stock": False,
        }
        with patch.object(main.repository, "stock_exists", return_value=True), patch.object(
            main.repository, "adjust_stock", return_value=(stock, context)
        ) as committed, patch.object(main, "publish_events", return_value=(False, [])):
            response = main.adjust_stock(
                main.AdjustmentRequest(
                    product_id=7,
                    quantity_delta=10,
                    minimum_quantity=2,
                    reason="Initial delivery",
                )
            )
        committed.assert_called_once()
        self.assertEqual(response["available_quantity"], 10)
        self.assertFalse(response["event_published"])
        self.assertIsNone(response["event_key"])

    def test_validation_errors_have_a_stable_code(self):
        with self.assertRaises(ValidationError):
            main.CreateReservationRequest(user_id="", items=[])
        self.assertIs(
            main.app.exception_handlers[RequestValidationError],
            main.validation_error_handler,
        )

    def test_openapi_contains_all_phase_two_routes(self):
        paths = main.app.openapi()["paths"]
        expected = {
            "/health",
            "/api/inventory/{product_id}",
            "/api/inventory/low-stock",
            "/api/inventory/adjustments",
            "/api/inventory/reservations",
            "/api/inventory/reservations/{reservation_id}",
            "/api/inventory/reservations/{reservation_id}/confirm",
            "/api/inventory/reservations/{reservation_id}/cancel",
        }
        self.assertTrue(expected.issubset(paths))
        self.assertIn("delete", paths["/api/inventory/reservations/{reservation_id}"])


if __name__ == "__main__":
    unittest.main()
