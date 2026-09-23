import logging
import os
from datetime import datetime, timezone
from typing import Any

import pyarrow as pa
from pymongo import MongoClient
from pymongo.collection import Collection

from common.runner import run_job
from common.s3_writer import upload_parquet, utc_now


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("identity-ingestor")

USERS_SCHEMA = pa.schema(
    [
        pa.field("user_id", pa.string(), nullable=False),
        pa.field("roles", pa.list_(pa.string()), nullable=False),
        pa.field("currency", pa.string()),
        pa.field("theme", pa.string()),
        pa.field("created_at", pa.timestamp("us", tz="UTC"), nullable=False),
        pa.field("snapshot_at", pa.timestamp("us", tz="UTC"), nullable=False),
    ]
)


def parse_timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def get_users_collection() -> Collection:
    client = MongoClient(
        os.getenv(
            "MONGODB_URI",
            "mongodb://hardtech_reader:hardtech_reader@mongodb:27017/hardtech_identity?authSource=hardtech_identity",
        ),
        serverSelectionTimeoutMS=int(os.getenv("MONGODB_TIMEOUT_MS", "5000")),
    )
    database = client[os.getenv("MONGODB_DATABASE", "hardtech_identity")]
    return database[os.getenv("MONGODB_USERS_COLLECTION", "users")]


def scan_all_users() -> list[dict[str, Any]]:
    batch_size = int(os.getenv("MONGODB_BATCH_SIZE", "1000"))
    projection = {
        "_id": 0,
        "user_id": 1,
        "roles": 1,
        "preferences": 1,
        "created_at": 1,
    }
    cursor = get_users_collection().find({}, projection).batch_size(batch_size)
    return list(cursor)


def build_user_records(
    users: list[dict[str, Any]], snapshot_at: datetime
) -> list[dict[str, Any]]:
    records = []
    for user in users:
        preferences = user.get("preferences", {})
        records.append(
            {
                "user_id": user["user_id"],
                "roles": [str(role) for role in user.get("roles", [])],
                "currency": preferences.get("currency"),
                "theme": preferences.get("theme"),
                "created_at": parse_timestamp(user["created_at"]),
                "snapshot_at": snapshot_at,
            }
        )
    return records


def extract_identity() -> None:
    snapshot_at = utc_now()
    users = scan_all_users()
    records = build_user_records(users, snapshot_at)

    key = upload_parquet(
        records,
        schema=USERS_SCHEMA,
        prefix=os.getenv("S3_OUTPUT_PREFIX", "processed/snapshots/users/"),
        dataset="users",
        snapshot_at=snapshot_at,
    )
    log.info("Identity snapshot completed: rows=%d key=%s", len(records), key)


if __name__ == "__main__":
    run_job("identity-ingestor", extract_identity)
