import json
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from botocore.exceptions import ClientError

from app.events import (
    INVENTORY_EVENT_TYPES,
    build_event,
    build_event_key,
    publish_event,
    serialize_event,
)


class FailingS3Client:
    def put_object(self, **kwargs):
        raise ClientError(
            {"Error": {"Code": "ServiceUnavailable", "Message": "temporary"}},
            "PutObject",
        )


class InventoryEventTests(unittest.TestCase):
    def test_all_required_inventory_event_types_are_supported(self):
        self.assertEqual(
            INVENTORY_EVENT_TYPES,
            {
                "STOCK_ADJUSTED",
                "STOCK_RESERVED",
                "STOCK_CONFIRMED",
                "STOCK_RELEASED",
                "RESERVATION_EXPIRED",
                "STOCK_RESTORED",
                "LOW_STOCK_DETECTED",
            },
        )

    def test_envelope_serialization_and_partitioned_key(self):
        event = build_event(
            "STOCK_ADJUSTED",
            {"quantity_delta": 5, "quantity_after": 12},
            product_id=7,
            occurred_at=datetime(2026, 9, 23, 15, 4, tzinfo=timezone.utc),
        )
        self.assertEqual(
            set(event),
            {
                "event_id",
                "event_type",
                "timestamp",
                "source",
                "user_id",
                "session_id",
                "product_id",
                "order_id",
                "payload",
            },
        )
        self.assertEqual(event["source"], "inventory-service")
        self.assertRegex(event["event_id"], r"^evt_[0-9a-f]{8}$")
        self.assertEqual(json.loads(serialize_event(event)), event)
        self.assertRegex(
            build_event_key("/raw/events/inventory/", event),
            rf"^raw/events/inventory/year=2026/month=09/day=23/stock_adjusted_{event['event_id']}\.json$",
        )

    def test_s3_failure_is_reported_without_raising(self):
        event = build_event("STOCK_RESERVED", {"items": []})
        with patch("app.events.get_s3_client", return_value=FailingS3Client()):
            self.assertIsNone(publish_event(event))


if __name__ == "__main__":
    unittest.main()
