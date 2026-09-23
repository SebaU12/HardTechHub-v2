import unittest
from datetime import datetime, timezone

from identity_ingestor import build_user_records


class IdentityIngestorTests(unittest.TestCase):
    def test_build_user_records_excludes_sensitive_mongodb_fields(self):
        snapshot_at = datetime(2026, 9, 23, 16, 0, tzinfo=timezone.utc)
        users = [
            {
                "_id": "mongo-id",
                "user_id": "usr_1",
                "email": "private@example.com",
                "password_hash": "never-export",
                "roles": ["customer"],
                "preferences": {"currency": "PEN", "theme": "dark"},
                "created_at": "2026-09-23T15:30:00Z",
            }
        ]

        records = build_user_records(users, snapshot_at)

        self.assertEqual(
            records,
            [
                {
                    "user_id": "usr_1",
                    "roles": ["customer"],
                    "currency": "PEN",
                    "theme": "dark",
                    "created_at": datetime(2026, 9, 23, 15, 30, tzinfo=timezone.utc),
                    "snapshot_at": snapshot_at,
                }
            ],
        )
        self.assertNotIn("email", records[0])
        self.assertNotIn("password_hash", records[0])


if __name__ == "__main__":
    unittest.main()
