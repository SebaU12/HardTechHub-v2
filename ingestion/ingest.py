import io
import json
import logging
import os
import random
import time
import uuid
from datetime import datetime, timezone

import pandas as pd
from botocore.exceptions import BotoCoreError, ClientError

from common.s3_writer import get_s3_client

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
log = logging.getLogger("ingestor")

S3_BUCKET = os.getenv("S3_BUCKET", "hardtech-datalake")
S3_EVENTS_PREFIX = os.getenv("S3_EVENTS_PREFIX", "raw/events/navigation/").strip("/")
S3_PROCESSED_PREFIX = os.getenv(
    "S3_PROCESSED_PREFIX", "processed/events/navigation/"
).strip("/")
BATCH_SIZE = int(os.getenv("BATCH_SIZE", "10"))
INTERVAL_SECONDS = int(os.getenv("INTERVAL_SECONDS", "30"))

# ORDER_CREATED is emitted by Order Service after a real order is committed.
EVENT_TYPES = ["PRODUCT_VIEW", "PRODUCT_SEARCH", "ADD_TO_CART", "REMOVE_FROM_CART"]
CATEGORIES = ["CPU", "GPU", "RAM", "Motherboard", "PSU", "Storage"]
PRODUCT_IDS = [1, 2, 3, 4, 5]
USER_IDS = [f"usr_{i:03d}" for i in range(1, 21)]


def make_event() -> dict:
    event_type = random.choice(EVENT_TYPES)
    product_id = random.choice(PRODUCT_IDS) if event_type != "PRODUCT_SEARCH" else None
    return {
        "event_id": f"evt_{uuid.uuid4().hex[:8]}",
        "event_type": event_type,
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": "synthetic-ingestor",
        "user_id": random.choice(USER_IDS),
        "session_id": f"sess_{uuid.uuid4().hex[:6]}",
        "product_id": product_id,
        "order_id": None,
        "payload": {"category": random.choice(CATEGORIES)},
    }


def s3_key(now: datetime) -> str:
    return (
        f"{S3_EVENTS_PREFIX}/year={now.year}/month={now.month:02d}"
        f"/day={now.day:02d}/events_{now.strftime('%H%M%S')}_{uuid.uuid4().hex[:6]}.json"
    )


def upload_raw(s3, events: list[dict], now: datetime) -> None:
    key = s3_key(now)
    # Glue/Athena's JSON SerDe expects one complete JSON record per line.
    body = "\n".join(json.dumps(event, ensure_ascii=False) for event in events) + "\n"
    s3.put_object(Bucket=S3_BUCKET, Key=key, Body=body.encode("utf-8"), ContentType="application/json")
    log.info("[RAW]       Uploaded %d events → s3://%s/%s", len(events), S3_BUCKET, key)


def upload_processed(s3, events: list[dict], now: datetime) -> None:
    df = pd.DataFrame(events)
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    df["product_id"] = pd.to_numeric(df["product_id"], errors="coerce").astype("Int64")

    buffer = io.BytesIO()
    df.to_parquet(buffer, engine="pyarrow", index=False)
    buffer.seek(0)

    suffix = f"{now.strftime('%H%M%S')}_{uuid.uuid4().hex[:6]}"
    key = (
        f"{S3_PROCESSED_PREFIX}/year={now.year}/month={now.month:02d}"
        f"/day={now.day:02d}/events_{suffix}.parquet"
    )
    s3.put_object(Bucket=S3_BUCKET, Key=key, Body=buffer.getvalue(), ContentType="application/octet-stream")
    log.info("[PROCESSED] Uploaded Parquet (%d rows) → s3://%s/%s", len(df), S3_BUCKET, key)


def main() -> None:
    endpoint = os.getenv("S3_ENDPOINT_URL") or "AWS"
    log.info("Starting ingestor | bucket=%s endpoint=%s batch=%d interval=%ds",
             S3_BUCKET, endpoint, BATCH_SIZE, INTERVAL_SECONDS)

    # Local Compose defines S3_ENDPOINT_URL and test credentials for LocalStack.
    # In AWS those variables are absent, so boto3 uses the EC2 instance role.
    s3 = get_s3_client()

    total = 0
    while True:
        now = datetime.now(timezone.utc)
        events = [make_event() for _ in range(BATCH_SIZE)]
        for e in events:
            log.info("  event: %s  user=%s  product=%s", e["event_type"], e["user_id"], e["product_id"])
        try:
            upload_raw(s3, events, now)
            upload_processed(s3, events, now)
            total += len(events)
            log.info("Total events uploaded so far: %d", total)
        except (BotoCoreError, ClientError) as exc:
            log.error("S3 upload failed: %s — retrying next cycle", exc)

        log.info("Sleeping %ds before next batch...", INTERVAL_SECONDS)
        time.sleep(INTERVAL_SECONDS)


if __name__ == "__main__":
    main()
