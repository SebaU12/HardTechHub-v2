import json
import logging
import os
import socket
from decimal import Decimal
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

import boto3
from botocore.exceptions import BotoCoreError, ClientError
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import pymysql

from app.events import build_event, build_event_key, serialize_event


log = logging.getLogger("order-service")


def get_connection() -> pymysql.connections.Connection:
    return pymysql.connect(
        host=os.getenv("MYSQL_HOST", "mysql"),
        port=int(os.getenv("MYSQL_PORT", "3306")),
        user=os.getenv("MYSQL_USER", "hardtech"),
        password=os.getenv("MYSQL_PASSWORD", "hardtech"),
        database=os.getenv("MYSQL_DATABASE", "hardtech_orders"),
        cursorclass=pymysql.cursors.DictCursor,
        autocommit=False,
    )


def _servers() -> list[dict[str, str]]:
    base = os.getenv("API_BASE_URL", "").strip()
    return [{"url": base, "description": "API Gateway / Local"}] if base else []


app = FastAPI(
    title="Order Service",
    version="1.0.0",
    docs_url="/orders/docs",
    openapi_url="/orders/openapi.json",
    servers=_servers(),
)


def get_catalog_service_url() -> str:
    return os.getenv("CATALOG_SERVICE_URL", "http://catalog-service:8002")


def get_s3_client() -> Any:
    kwargs: dict[str, Any] = {
        "region_name": os.getenv("AWS_DEFAULT_REGION", "us-east-1"),
    }
    if endpoint := os.getenv("S3_ENDPOINT_URL"):
        kwargs["endpoint_url"] = endpoint
    if access_key := os.getenv("AWS_ACCESS_KEY_ID"):
        kwargs["aws_access_key_id"] = access_key
    if secret_key := os.getenv("AWS_SECRET_ACCESS_KEY"):
        kwargs["aws_secret_access_key"] = secret_key
    return boto3.client("s3", **kwargs)


def publish_order_event(event: dict[str, Any]) -> str | None:
    key = build_event_key(os.getenv("S3_EVENTS_PREFIX", "raw/events/orders/"), event)

    try:
        get_s3_client().put_object(
            Bucket=os.getenv("S3_BUCKET", "hardtech-datalake"),
            Key=key,
            Body=serialize_event(event),
            ContentType="application/json",
        )
    except (BotoCoreError, ClientError) as exc:
        log.error(
            "The business operation was committed, but event %s could not be written to S3: %s",
            event["event_type"],
            exc,
        )
        return None

    log.info(
        "Published %s at s3://%s/%s",
        event["event_type"],
        os.getenv("S3_BUCKET", "hardtech-datalake"),
        key,
    )
    return key


def publish_order_created_event(
    order_id: int,
    user_id: str,
    total_amount: Decimal,
    items: list[dict[str, Any]],
) -> str | None:
    event = build_event(
        event_type="ORDER_CREATED",
        source="order-service",
        user_id=user_id,
        order_id=order_id,
        payload={
            "status": "PENDING",
            "total_amount": str(total_amount),
            "item_count": sum(int(item["quantity"]) for item in items),
        },
    )
    return publish_order_event(event)


def publish_order_status_changed_event(order: dict[str, Any], new_status: str) -> str | None:
    event = build_event(
        event_type="ORDER_STATUS_CHANGED",
        source="order-service",
        user_id=order["user_id"],
        order_id=order["id"],
        payload={
            "previous_status": order["status"],
            "new_status": new_status,
            "total_amount": str(order["total_amount"]),
        },
    )
    return publish_order_event(event)


def fetch_product_snapshot(product_id: int) -> dict[str, Any]:
    product_url = f"{get_catalog_service_url()}/api/products/{product_id}"
    try:
        with urlopen(product_url, timeout=5) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        if exc.code == 404:
            raise HTTPException(status_code=400, detail=f"Product {product_id} not found") from exc
        raise HTTPException(status_code=502, detail="Catalog Service error") from exc
    except URLError as exc:
        raise HTTPException(status_code=503, detail="Catalog Service unavailable") from exc


class OrderItemRequest(BaseModel):
    product_id: int
    quantity: int


class CreateOrderRequest(BaseModel):
    user_id: str
    items: list[OrderItemRequest]


@app.get("/health")
def healthcheck() -> dict[str, str]:
    return {
        "service": "order-service",
        "status": "healthy",
        "version": "1.0.0",
        "instance": os.getenv("INSTANCE_ID", socket.gethostname()),
    }


@app.post("/api/orders")
def create_order(payload: CreateOrderRequest) -> dict[str, Any]:
    if not payload.items:
        raise HTTPException(status_code=400, detail="Order items are required")

    order_snapshots = []
    subtotal = Decimal("0.00")
    for item in payload.items:
        product = fetch_product_snapshot(item.product_id)
        unit_price = Decimal(str(product["price"]))
        item_subtotal = unit_price * item.quantity
        order_snapshots.append(
            {
                "product_id": item.product_id,
                "product_sku": product["sku"],
                "product_name": product["name"],
                "quantity": item.quantity,
                "unit_price": unit_price,
                "subtotal": item_subtotal,
            }
        )
        subtotal += item_subtotal

    tax = (subtotal * Decimal("0.18")).quantize(Decimal("0.01"))
    shipping_cost = Decimal("25.00")
    total_amount = subtotal + tax + shipping_cost

    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO orders (user_id, status, subtotal, tax, shipping_cost, total_amount)
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (payload.user_id, "PENDING", str(subtotal), str(tax), str(shipping_cost), str(total_amount)),
            )
            order_id = cursor.lastrowid

            for item in order_snapshots:
                cursor.execute(
                    """
                    INSERT INTO order_items
                    (order_id, product_id, product_sku, product_name, quantity, unit_price, subtotal)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        order_id,
                        item["product_id"],
                        item["product_sku"],
                        item["product_name"],
                        item["quantity"],
                        str(item["unit_price"]),
                        str(item["subtotal"]),
                    ),
                )

        conn.commit()
    except Exception as exc:
        conn.rollback()
        raise HTTPException(status_code=500, detail="MySQL error") from exc
    finally:
        conn.close()

    event_key = publish_order_created_event(
        order_id=order_id,
        user_id=payload.user_id,
        total_amount=total_amount,
        items=order_snapshots,
    )

    return {
        "order_id": order_id,
        "status": "PENDING",
        "total_amount": str(total_amount),
        "event_published": event_key is not None,
        "event_key": event_key,
    }


@app.get("/api/orders/user/{user_id}")
def get_orders_by_user(user_id: str) -> Any:
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT * FROM orders WHERE user_id = %s ORDER BY created_at DESC",
                (user_id,),
            )
            orders = cursor.fetchall()
    finally:
        conn.close()
    return list(orders)


VALID_STATUSES = {"PENDING", "PAID", "SHIPPED", "CANCELLED"}


class UpdateStatusRequest(BaseModel):
    status: str


@app.patch("/api/orders/{order_id}/status")
def update_order_status(order_id: int, payload: UpdateStatusRequest) -> dict[str, Any]:
    if payload.status not in VALID_STATUSES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid status. Must be one of: {', '.join(sorted(VALID_STATUSES))}",
        )
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT id, user_id, status, total_amount FROM orders WHERE id = %s",
                (order_id,),
            )
            order: dict[str, Any] = cursor.fetchone()  # type: ignore[assignment]
            if not order:
                raise HTTPException(status_code=404, detail="Order not found")
            cursor.execute(
                "UPDATE orders SET status = %s WHERE id = %s",
                (payload.status, order_id),
            )
        conn.commit()
    except HTTPException:
        raise
    except Exception as exc:
        conn.rollback()
        raise HTTPException(status_code=500, detail="MySQL error") from exc
    finally:
        conn.close()

    event_key = publish_order_status_changed_event(order, payload.status)
    return {
        "order_id": order_id,
        "status": payload.status,
        "event_published": event_key is not None,
        "event_key": event_key,
    }


@app.get("/api/orders/{order_id}")
def get_order(order_id: int) -> dict[str, Any]:
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT * FROM orders WHERE id = %s", (order_id,))
            order = cursor.fetchone()
            if not order:
                raise HTTPException(status_code=404, detail="Order not found")

            cursor.execute("SELECT * FROM order_items WHERE order_id = %s ORDER BY id ASC", (order_id,))
            items = cursor.fetchall()
    finally:
        conn.close()

    return {"order": order, "items": items}
