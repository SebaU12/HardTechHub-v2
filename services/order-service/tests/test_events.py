import json
import unittest
from datetime import datetime, timezone

from app.events import build_event, build_event_key, serialize_event


class OrderEventTests(unittest.TestCase):
    def test_event_envelope_key_and_serialization(self):
        event = build_event(
            "ORDER_CREATED",
            "order-service",
            {"status": "PENDING", "total_amount": "100.00", "item_count": 1},
            user_id="usr_1",
            order_id=25,
            occurred_at=datetime(2026, 1, 2, 3, 4, tzinfo=timezone.utc),
        )
        self.assertEqual(event["source"], "order-service")
        self.assertEqual(event["order_id"], 25)
        self.assertRegex(event["event_id"], r"^evt_[0-9a-f]{8}$")
        self.assertEqual(
            build_event_key("raw/events/orders", event),
            f"raw/events/orders/year=2026/month=01/day=02/order_created_{event['event_id']}.json",
        )
        self.assertEqual(json.loads(serialize_event(event)), event)


if __name__ == "__main__":
    unittest.main()
