from __future__ import annotations

import json
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Any

import boto3
from botocore.exceptions import BotoCoreError, ClientError


log = logging.getLogger("inventory-service.events")

INVENTORY_EVENT_TYPES = frozenset(
    {
        "STOCK_ADJUSTED",
        "STOCK_RESERVED",
        "STOCK_CONFIRMED",
        "STOCK_RELEASED",
        "RESERVATION_EXPIRED",
        "STOCK_RESTORED",
        "LOW_STOCK_DETECTED",
    }
)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def build_event(
    event_type: str,
    payload: dict[str, Any],
    *,
    user_id: str | None = None,
    session_id: str | None = None,
    product_id: int | None = None,
    order_id: int | None = None,
    occurred_at: datetime | None = None,
) -> dict[str, Any]:
    if event_type not in INVENTORY_EVENT_TYPES:
        raise ValueError(f"Unsupported inventory event type: {event_type}")
    timestamp = occurred_at or utc_now()
    return {
        "event_id": f"evt_{uuid.uuid4().hex[:8]}",
        "event_type": event_type,
        "timestamp": timestamp.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": "inventory-service",
        "user_id": user_id,
        "session_id": session_id,
        "product_id": product_id,
        "order_id": order_id,
        "payload": payload,
    }


def build_event_key(prefix: str, event: dict[str, Any]) -> str:
    timestamp = datetime.strptime(event["timestamp"], "%Y-%m-%dT%H:%M:%SZ")
    normalized_prefix = prefix.strip("/")
    filename = f"{event['event_type'].lower()}_{event['event_id']}.json"
    return (
        f"{normalized_prefix}/year={timestamp.year}/month={timestamp.month:02d}"
        f"/day={timestamp.day:02d}/{filename}"
    )


def serialize_event(event: dict[str, Any]) -> bytes:
    return json.dumps(event, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def get_s3_client() -> Any:
    options: dict[str, Any] = {
        "region_name": os.getenv("AWS_DEFAULT_REGION", "us-east-1"),
    }
    if endpoint := os.getenv("S3_ENDPOINT_URL"):
        options["endpoint_url"] = endpoint
    if access_key := os.getenv("AWS_ACCESS_KEY_ID"):
        options["aws_access_key_id"] = access_key
    if secret_key := os.getenv("AWS_SECRET_ACCESS_KEY"):
        options["aws_secret_access_key"] = secret_key
    return boto3.client("s3", **options)


def publish_event(event: dict[str, Any]) -> str | None:
    key = build_event_key(
        os.getenv("S3_EVENTS_PREFIX", "raw/events/inventory/"),
        event,
    )
    try:
        get_s3_client().put_object(
            Bucket=os.getenv("S3_BUCKET", "hardtech-datalake"),
            Key=key,
            Body=serialize_event(event),
            ContentType="application/json",
        )
    except (BotoCoreError, ClientError) as exc:
        log.error(
            "Inventory operation committed but event_type=%s event_id=%s was not published: %s",
            event["event_type"],
            event["event_id"],
            exc,
        )
        return None

    log.info(
        "Published event_type=%s event_id=%s key=%s",
        event["event_type"],
        event["event_id"],
        key,
    )
    return key


def publish_events(events: list[dict[str, Any]]) -> tuple[bool, list[str]]:
    keys: list[str] = []
    all_published = True
    for event in events:
        key = publish_event(event)
        if key is None:
            all_published = False
        else:
            keys.append(key)
    return all_published, keys
