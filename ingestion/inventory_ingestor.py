import logging
import os
from datetime import datetime
from typing import Any

import psycopg2
import pyarrow as pa
from psycopg2.extras import RealDictCursor

from common.runner import run_job
from common.s3_writer import as_utc, upload_parquet, utc_now


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("inventory-ingestor")

INVENTORY_SCHEMA = pa.schema(
    [
        pa.field("product_id", pa.int64(), nullable=False),
        pa.field("available_quantity", pa.int64(), nullable=False),
        pa.field("reserved_quantity", pa.int64(), nullable=False),
        pa.field("sellable_quantity", pa.int64(), nullable=False),
        pa.field("minimum_quantity", pa.int64(), nullable=False),
        pa.field("low_stock", pa.bool_(), nullable=False),
        pa.field("version", pa.int64(), nullable=False),
        pa.field("created_at", pa.timestamp("us", tz="UTC"), nullable=False),
        pa.field("updated_at", pa.timestamp("us", tz="UTC"), nullable=False),
        pa.field("snapshot_at", pa.timestamp("us", tz="UTC"), nullable=False),
    ]
)


def build_inventory_records(
    rows: list[dict[str, Any]], snapshot_at: datetime
) -> list[dict[str, Any]]:
    records = []
    for row in rows:
        available = int(row["available_quantity"])
        reserved = int(row["reserved_quantity"])
        minimum = int(row["minimum_quantity"])
        sellable = available - reserved
        records.append(
            {
                "product_id": int(row["product_id"]),
                "available_quantity": available,
                "reserved_quantity": reserved,
                "sellable_quantity": sellable,
                "minimum_quantity": minimum,
                "low_stock": sellable <= minimum,
                "version": int(row["version"]),
                "created_at": as_utc(row["created_at"]),
                "updated_at": as_utc(row["updated_at"]),
                "snapshot_at": snapshot_at,
            }
        )
    return records


def scan_inventory() -> list[dict[str, Any]]:
    connection = psycopg2.connect(
        host=os.getenv("POSTGRES_HOST", "postgres"),
        port=int(os.getenv("POSTGRES_PORT", "5432")),
        dbname=os.getenv("POSTGRES_DB", "hardtech_inventory"),
        user=os.getenv("POSTGRES_USER", "hardtech_reader"),
        password=os.getenv("POSTGRES_PASSWORD", "hardtech_reader"),
        connect_timeout=int(os.getenv("POSTGRES_CONNECT_TIMEOUT_SECONDS", "5")),
    )
    connection.set_session(readonly=True, autocommit=True)
    try:
        with connection.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(
                """
                SELECT product_id, available_quantity, reserved_quantity,
                       minimum_quantity, version, created_at, updated_at
                FROM inventory_stock
                ORDER BY product_id
                """
            )
            return list(cursor.fetchall())
    finally:
        connection.close()


def extract_inventory() -> None:
    snapshot_at = utc_now()
    records = build_inventory_records(scan_inventory(), snapshot_at)
    key = upload_parquet(
        records,
        schema=INVENTORY_SCHEMA,
        prefix=os.getenv("S3_OUTPUT_PREFIX", "processed/snapshots/inventory/"),
        dataset="inventory",
        snapshot_at=snapshot_at,
    )
    log.info("Inventory snapshot completed: rows=%d key=%s", len(records), key)


if __name__ == "__main__":
    run_job("inventory-ingestor", extract_inventory)
