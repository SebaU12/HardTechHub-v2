import json
import uuid
from datetime import datetime, timezone
from typing import Any


def build_event(
    event_type: str,
    source: str,
    payload: dict[str, Any],
    *,
    user_id: str | None = None,
    session_id: str | None = None,
    product_id: int | None = None,
    order_id: int | None = None,
    occurred_at: datetime | None = None,
) -> dict[str, Any]:
    timestamp = occurred_at or datetime.now(timezone.utc)
    return {
        "event_id": f"evt_{uuid.uuid4().hex[:8]}",
        "event_type": event_type,
        "timestamp": timestamp.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": source,
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
