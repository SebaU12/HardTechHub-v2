import logging
import os
from decimal import Decimal

import pyarrow as pa
import pymysql

from common.runner import run_job
from common.s3_writer import as_utc, upload_parquet, utc_now


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("orders-ingestor")

ORDERS_SCHEMA = pa.schema(
    [
        pa.field("id", pa.int64(), nullable=False),
        pa.field("user_id", pa.string(), nullable=False),
        pa.field("status", pa.string(), nullable=False),
        pa.field("subtotal", pa.decimal128(10, 2), nullable=False),
        pa.field("tax", pa.decimal128(10, 2), nullable=False),
        pa.field("shipping_cost", pa.decimal128(10, 2), nullable=False),
        pa.field("total_amount", pa.decimal128(10, 2), nullable=False),
        pa.field("created_at", pa.timestamp("us", tz="UTC"), nullable=False),
        pa.field("updated_at", pa.timestamp("us", tz="UTC"), nullable=False),
        pa.field("snapshot_at", pa.timestamp("us", tz="UTC"), nullable=False),
    ]
)

ORDER_ITEMS_SCHEMA = pa.schema(
    [
        pa.field("id", pa.int64(), nullable=False),
        pa.field("order_id", pa.int64(), nullable=False),
        pa.field("product_id", pa.int64(), nullable=False),
        pa.field("product_sku", pa.string(), nullable=False),
        pa.field("product_name", pa.string(), nullable=False),
        pa.field("quantity", pa.int64(), nullable=False),
        pa.field("unit_price", pa.decimal128(10, 2), nullable=False),
        pa.field("subtotal", pa.decimal128(10, 2), nullable=False),
        pa.field("snapshot_at", pa.timestamp("us", tz="UTC"), nullable=False),
    ]
)


def money(value: Decimal) -> Decimal:
    return Decimal(value).quantize(Decimal("0.01"))


def extract_orders() -> None:
    snapshot_at = utc_now()
    connection = pymysql.connect(
        host=os.getenv("MYSQL_HOST", "mysql"),
        port=int(os.getenv("MYSQL_PORT", "3306")),
        user=os.getenv("MYSQL_USER", "hardtech"),
        password=os.getenv("MYSQL_PASSWORD", "hardtech"),
        database=os.getenv("MYSQL_DATABASE", "hardtech_orders"),
        cursorclass=pymysql.cursors.DictCursor,
        autocommit=True,
    )
    try:
        with connection.cursor() as cursor:
            cursor.execute("SET SESSION TRANSACTION READ ONLY")
            cursor.execute("SELECT * FROM orders ORDER BY id")
            order_rows = cursor.fetchall()
            cursor.execute("SELECT * FROM order_items ORDER BY id")
            item_rows = cursor.fetchall()
    finally:
        connection.close()

    orders = [
        {
            "id": int(row["id"]),
            "user_id": row["user_id"],
            "status": row["status"],
            "subtotal": money(row["subtotal"]),
            "tax": money(row["tax"]),
            "shipping_cost": money(row["shipping_cost"]),
            "total_amount": money(row["total_amount"]),
            "created_at": as_utc(row["created_at"]),
            "updated_at": as_utc(row["updated_at"]),
            "snapshot_at": snapshot_at,
        }
        for row in order_rows
    ]
    order_items = [
        {
            "id": int(row["id"]),
            "order_id": int(row["order_id"]),
            "product_id": int(row["product_id"]),
            "product_sku": row["product_sku"],
            "product_name": row["product_name"],
            "quantity": int(row["quantity"]),
            "unit_price": money(row["unit_price"]),
            "subtotal": money(row["subtotal"]),
            "snapshot_at": snapshot_at,
        }
        for row in item_rows
    ]

    orders_key = upload_parquet(
        orders,
        schema=ORDERS_SCHEMA,
        prefix=os.getenv("S3_ORDERS_PREFIX", "processed/snapshots/orders/"),
        dataset="orders",
        snapshot_at=snapshot_at,
    )
    items_key = upload_parquet(
        order_items,
        schema=ORDER_ITEMS_SCHEMA,
        prefix=os.getenv("S3_ORDER_ITEMS_PREFIX", "processed/snapshots/order_items/"),
        dataset="order_items",
        snapshot_at=snapshot_at,
    )
    log.info(
        "Orders snapshot completed: orders=%d items=%d keys=%s,%s",
        len(orders),
        len(order_items),
        orders_key,
        items_key,
    )


if __name__ == "__main__":
    run_job("orders-ingestor", extract_orders)
