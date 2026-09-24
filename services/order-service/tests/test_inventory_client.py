import io
import json
import unittest
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError, URLError

from app.inventory_client import InventoryClient, InventoryClientError, InventoryUnavailable


class _Response:
    def __init__(self, payload, status=200):
        self.payload = payload
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


class InventoryClientTests(unittest.TestCase):
    def setUp(self):
        self.client = InventoryClient()
        self.client.base_url = "http://inventory:8006"
        self.client.retry_delays = (0, 0)

    @patch("app.inventory_client.urlopen")
    def test_reserve_sends_idempotency_key_and_normalized_payload(self, urlopen):
        urlopen.return_value = _Response(
            {"reservation_id": "res-1", "status": "ACTIVE"}
        )

        result = self.client.reserve(
            "order-key-00000001", "usr_1", [{"product_id": 1, "quantity": 2}]
        )

        self.assertEqual(result["reservation_id"], "res-1")
        request = urlopen.call_args.args[0]
        self.assertEqual(request.method, "POST")
        self.assertEqual(request.full_url, "http://inventory:8006/api/inventory/reservations")
        self.assertEqual(request.headers["Idempotency-key"], "order-key-00000001")
        self.assertEqual(
            json.loads(request.data),
            {"user_id": "usr_1", "items": [{"product_id": 1, "quantity": 2}]},
        )

    @patch("app.inventory_client.urlopen")
    def test_business_conflict_is_not_retried(self, urlopen):
        body = io.BytesIO(
            json.dumps(
                {
                    "detail": {
                        "code": "INSUFFICIENT_STOCK",
                        "message": "There is not enough stock",
                    }
                }
            ).encode("utf-8")
        )
        urlopen.side_effect = HTTPError("http://inventory", 409, "Conflict", {}, body)

        with self.assertRaises(InventoryClientError) as raised:
            self.client.reserve("order-key-00000002", "usr_1", [])

        self.assertEqual(raised.exception.status_code, 409)
        self.assertEqual(raised.exception.code, "INSUFFICIENT_STOCK")
        self.assertEqual(urlopen.call_count, 1)

    @patch("app.inventory_client.time.sleep")
    @patch("app.inventory_client.urlopen")
    def test_network_failures_are_retried_then_reported_unavailable(self, urlopen, sleep):
        urlopen.side_effect = URLError("connection refused")

        with self.assertRaises(InventoryUnavailable):
            self.client.get_reservation("res-1")

        self.assertEqual(urlopen.call_count, 3)
        self.assertEqual(sleep.call_count, 2)

    @patch("app.inventory_client.time.sleep")
    @patch("app.inventory_client.urlopen")
    def test_server_error_can_recover_on_retry(self, urlopen, _sleep):
        error = HTTPError(
            "http://inventory", 503, "Unavailable", {}, io.BytesIO(b"{}")
        )
        urlopen.side_effect = [error, _Response({"status": "CONFIRMED", "order_id": 7})]

        result = self.client.confirm("res-1", 7)

        self.assertEqual(result["status"], "CONFIRMED")
        self.assertEqual(urlopen.call_count, 2)


if __name__ == "__main__":
    unittest.main()
