import json
import logging
import os
from decimal import Decimal

import psycopg2
import pyarrow as pa
from psycopg2.extras import RealDictCursor

from common.runner import run_job
from common.s3_writer import as_utc, upload_parquet, utc_now


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("catalog-ingestor")

PRODUCTS_SCHEMA = pa.schema(
    [
        pa.field("id", pa.int64(), nullable=False),
        pa.field("sku", pa.string(), nullable=False),
        pa.field("name", pa.string(), nullable=False),
        pa.field("description", pa.string()),
        pa.field("price", pa.decimal128(10, 2), nullable=False),
        pa.field("specs", pa.string(), nullable=False),
        pa.field("image_url", pa.string()),
        pa.field("category", pa.string(), nullable=False),
        pa.field("brand", pa.string(), nullable=False),
        pa.field("is_active", pa.bool_(), nullable=False),
        pa.field("created_at", pa.timestamp("us", tz="UTC"), nullable=False),
        pa.field("snapshot_at", pa.timestamp("us", tz="UTC"), nullable=False),
    ]
)


def extract_catalog() -> None:
    snapshot_at = utc_now()
    connection = psycopg2.connect(
        host=os.getenv("POSTGRES_HOST", "postgres"),
        port=int(os.getenv("POSTGRES_PORT", "5432")),
        dbname=os.getenv("POSTGRES_DB", "hardtech_catalog"),
        user=os.getenv("POSTGRES_USER", "hardtech"),
        password=os.getenv("POSTGRES_PASSWORD", "hardtech"),
    )
    connection.set_session(readonly=True, autocommit=True)
    try:
        with connection.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(
                """
                SELECT p.id, p.sku, p.name, p.description, p.price, p.specs,
                       p.image_url, p.is_active, p.created_at,
                       c.name AS category, b.name AS brand
                FROM products p
                JOIN categories c ON c.id = p.category_id
                JOIN brands b ON b.id = p.brand_id
                ORDER BY p.id
                """
            )
            rows = cursor.fetchall()
    finally:
        connection.close()

    records = [
        {
            "id": int(row["id"]),
            "sku": row["sku"],
            "name": row["name"],
            "description": row["description"],
            "price": Decimal(row["price"]).quantize(Decimal("0.01")),
            "specs": json.dumps(row["specs"], ensure_ascii=False, sort_keys=True),
            "image_url": row["image_url"],
            "category": row["category"],
            "brand": row["brand"],
            "is_active": bool(row["is_active"]),
            "created_at": as_utc(row["created_at"]),
            "snapshot_at": snapshot_at,
        }
        for row in rows
    ]
    key = upload_parquet(
        records,
        schema=PRODUCTS_SCHEMA,
        prefix=os.getenv("S3_OUTPUT_PREFIX", "processed/snapshots/products/"),
        dataset="products",
        snapshot_at=snapshot_at,
    )
    log.info("Catalog snapshot completed: rows=%d key=%s", len(records), key)


if __name__ == "__main__":
    run_job("catalog-ingestor", extract_catalog)
