import json
import unittest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from fastapi import HTTPException
from pymongo.errors import DuplicateKeyError

from app import main
from app.events import build_event, build_event_key, serialize_event


class IdentityEventTests(unittest.TestCase):
    def test_event_envelope_and_partitioned_key(self):
        occurred_at = datetime(2026, 9, 23, 15, 30, tzinfo=timezone.utc)
        event = build_event(
            "USER_REGISTERED",
            "identity-service",
            {"roles": ["customer"]},
            user_id="usr_1",
            occurred_at=occurred_at,
        )
        self.assertRegex(event["event_id"], r"^evt_[0-9a-f]{8}$")
        self.assertEqual(event["timestamp"], "2026-09-23T15:30:00Z")
        self.assertEqual(
            build_event_key("/raw/events/identity/", event),
            f"raw/events/identity/year=2026/month=09/day=23/user_registered_{event['event_id']}.json",
        )
        self.assertEqual(json.loads(serialize_event(event)), event)

    def test_registered_event_excludes_sensitive_fields(self):
        item = {
            "user_id": "usr_1",
            "email": "secret@example.com",
            "password_hash": "never-export-this",
            "roles": ["customer"],
            "preferences": {"currency": "PEN", "theme": "dark"},
            "created_at": "2026-09-23T15:30:00+00:00",
        }
        serialized = serialize_event(main.build_user_registered_event(item)).decode("utf-8")
        self.assertNotIn("secret@example.com", serialized)
        self.assertNotIn("never-export-this", serialized)
        payload = json.loads(serialized)["payload"]
        self.assertEqual(set(payload), {"roles", "currency", "theme", "registered_at"})

    @patch("app.main.publish_user_registered_event", return_value="raw/event.json")
    @patch("app.main.hash_password", return_value="hashed")
    @patch("app.main.get_users_collection")
    def test_register_inserts_native_mongodb_document(
        self, get_collection, _hash_password, _publish_event
    ):
        collection = MagicMock()
        get_collection.return_value = collection

        response = main.register(
            main.RegisterRequest(email="new.user@example.com", password="secret")
        )

        inserted = collection.insert_one.call_args.args[0]
        self.assertEqual(inserted["user_id"], "new.user")
        self.assertEqual(inserted["email"], "new.user@example.com")
        self.assertEqual(inserted["roles"], ["customer"])
        self.assertEqual(inserted["password_hash"], "hashed")
        self.assertTrue(response["event_published"])

    @patch("app.main.hash_password", return_value="hashed")
    @patch("app.main.get_users_collection")
    def test_register_maps_duplicate_index_to_controlled_error(
        self, get_collection, _hash_password
    ):
        get_collection.return_value.insert_one.side_effect = DuplicateKeyError("duplicate")

        with self.assertRaises(HTTPException) as raised:
            main.register(main.RegisterRequest(email="duplicate@example.com", password="secret"))

        self.assertEqual(raised.exception.status_code, 400)
        self.assertEqual(raised.exception.detail, "User already exists")

    @patch("app.main.build_access_token", return_value="token")
    @patch("app.main.verify_password", return_value=True)
    @patch("app.main.get_users_collection")
    def test_login_queries_unique_email_index(
        self, get_collection, _verify_password, _build_token
    ):
        get_collection.return_value.find_one.return_value = {
            "user_id": "usr_1",
            "email": "user@example.com",
            "password_hash": "hashed",
            "roles": ["customer"],
        }

        response = main.login(main.LoginRequest(email="user@example.com", password="secret"))

        get_collection.return_value.find_one.assert_called_once_with(
            {"email": "user@example.com"}
        )
        self.assertEqual(response, {"access_token": "token", "token_type": "bearer"})


if __name__ == "__main__":
    unittest.main()
