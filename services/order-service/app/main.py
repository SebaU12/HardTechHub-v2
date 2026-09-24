from __future__ import annotations

import hashlib
import json
import logging
import os
import socket
from decimal import Decimal
from typing import Annotated, Any
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

import boto3
import pymysql
from botocore.exceptions import BotoCoreError, ClientError
from fastapi import FastAPI, Header, HTTPException, Response, status
from pydantic import BaseModel, Field

from app.events import build_event, build_event_key, serialize_event
from app.inventory_client import (
    InventoryClient,
    InventoryClientError,
    InventoryUnavailable,
)


log = logging.getLogger("order-service")
inventory_client = InventoryClient()


def get_connection() -> pymysql.connections.Connection:
    return pymysql.connect(
        host=os.getenv("MYSQL_HOST", "mysql"),
        port=int(os.getenv("MYSQL_PORT", "3306")),
        user=os.getenv("MYSQL_USER", "hardtech"),
        password=os.getenv("MYSQL_PASSWORD", "hardtech"),
        database=os.getenv("MYSQL_DATABASE", "hardtech_orders"),
        cursorclass=pymysql.cursors.DictCursor,
        autocommit=False,
        connect_timeout=int(os.getenv("MYSQL_CONNECT_TIMEOUT_SECONDS", "3")),
        read_timeout=int(os.getenv("MYSQL_READ_TIMEOUT_SECONDS", "5")),
        write_timeout=int(os.getenv("MYSQL_WRITE_TIMEOUT_SECONDS", "5")),
    )


def _servers() -> list[dict[str, str]]:
    base = os.getenv("API_BASE_URL", "").strip()
    return [{"url": base, "description": "API Gateway / Local"}] if base else []


app = FastAPI(
    title="Order Service",
    version="1.1.0",
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


def publish_order_status_changed_event(
    order: dict[str, Any], new_status: str
) -> str | None:
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
            raise HTTPException(
                status_code=400, detail=f"Product {product_id} not found"
            ) from exc
        raise HTTPException(status_code=502, detail="Catalog Service error") from exc
    except (URLError, TimeoutError) as exc:
        raise HTTPException(
            status_code=503, detail="Catalog Service unavailable"
        ) from exc


class OrderItemRequest(BaseModel):
    product_id: int = Field(gt=0)
    quantity: int = Field(ge=1, le=1000)


class CreateOrderRequest(BaseModel):
    user_id: str = Field(min_length=1, max_length=80)
    items: list[OrderItemRequest] = Field(min_length=1)


class UpdateStatusRequest(BaseModel):
    status: str


def normalize_items(items: list[OrderItemRequest]) -> list[dict[str, int]]:
    consolidated: dict[int, int] = {}
    for item in items:
        consolidated[item.product_id] = consolidated.get(item.product_id, 0) + item.quantity
        if consolidated[item.product_id] > 1000:
            raise HTTPException(
                status_code=422,
                detail={
                    "code": "INVALID_ORDER_QUANTITY",
                    "message": "The consolidated quantity cannot exceed 1000",
                    "product_id": item.product_id,
                },
            )
    return [
        {"product_id": product_id, "quantity": consolidated[product_id]}
        for product_id in sorted(consolidated)
    ]


def order_request_hash(user_id: str, items: list[dict[str, int]]) -> str:
    canonical = json.dumps(
        {"user_id": user_id, "items": items},
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def inventory_error_to_http(error: InventoryClientError) -> HTTPException:
    detail = dict(error.detail)
    if error.code == "INVENTORY_NOT_FOUND":
        detail["code"] = "STOCK_NOT_INITIALIZED"
        detail["message"] = "Inventory was not initialized for one or more products"
        return HTTPException(status_code=409, detail=detail)
    if error.status_code == 409:
        return HTTPException(status_code=409, detail=detail)
    if error.status_code in {400, 422}:
        return HTTPException(status_code=400, detail=detail)
    return HTTPException(status_code=502, detail=detail)


def inventory_unavailable_detail(
    *, order_id: int | None = None, reservation_id: str | None = None
) -> dict[str, Any]:
    detail: dict[str, Any] = {
        "code": "INVENTORY_UNAVAILABLE",
        "message": "Inventory Service is unavailable; retry with the same Idempotency-Key",
    }
    if order_id is not None:
        detail["order_id"] = order_id
    if reservation_id is not None:
        detail["reservation_id"] = reservation_id
    return detail


def find_order_by_idempotency_key(key: str) -> dict[str, Any] | None:
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT * FROM orders WHERE idempotency_key = %s", (key,))
            return cursor.fetchone()
    finally:
        conn.close()


def load_order_items(order_id: int) -> list[dict[str, Any]]:
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT * FROM order_items WHERE order_id = %s ORDER BY id", (order_id,)
            )
            return list(cursor.fetchall())
    finally:
        conn.close()


def set_inventory_status(
    order_id: int,
    inventory_status: str,
    *,
    order_status: str | None = None,
) -> None:
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            if order_status is None:
                cursor.execute(
                    "UPDATE orders SET inventory_status = %s WHERE id = %s",
                    (inventory_status, order_id),
                )
            else:
                cursor.execute(
                    "UPDATE orders SET inventory_status = %s, status = %s WHERE id = %s",
                    (inventory_status, order_status, order_id),
                )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def ensure_order_created_event(order_id: int) -> str | None:
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT * FROM orders WHERE id = %s FOR UPDATE", (order_id,))
            order = cursor.fetchone()
            if order is None:
                raise HTTPException(status_code=404, detail="Order not found")
            if order["order_event_key"]:
                return str(order["order_event_key"])
            cursor.execute(
                "SELECT * FROM order_items WHERE order_id = %s ORDER BY id", (order_id,)
            )
            items = list(cursor.fetchall())
            event_key = publish_order_created_event(
                order_id=order_id,
                user_id=order["user_id"],
                total_amount=order["total_amount"],
                items=items,
            )
            if event_key is not None:
                cursor.execute(
                    "UPDATE orders SET order_event_key = %s WHERE id = %s",
                    (event_key, order_id),
                )
        conn.commit()
        return event_key
    except HTTPException:
        conn.rollback()
        raise
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def order_response(order: dict[str, Any], event_key: str | None) -> dict[str, Any]:
    return {
        "order_id": int(order["id"]),
        "status": order["status"],
        "total_amount": str(order["total_amount"]),
        "inventory_reservation_id": order["inventory_reservation_id"],
        "inventory_status": order["inventory_status"],
        "event_published": event_key is not None,
        "event_key": event_key,
    }


def reconcile_confirmation(order: dict[str, Any]) -> dict[str, Any]:
    order_id = int(order["id"])
    reservation_id = str(order["inventory_reservation_id"])
    try:
        confirmation = inventory_client.confirm(reservation_id, order_id)
    except InventoryClientError as exc:
        if exc.code not in {"RESERVATION_NOT_ACTIVE", "RESERVATION_NOT_FOUND"}:
            raise inventory_error_to_http(exc) from exc
        try:
            reservation = inventory_client.get_reservation(reservation_id)
        except InventoryClientError as get_exc:
            raise inventory_error_to_http(get_exc) from get_exc
        except InventoryUnavailable as get_exc:
            set_inventory_status(order_id, "CONFIRMATION_PENDING")
            raise HTTPException(
                status_code=503,
                detail=inventory_unavailable_detail(
                    order_id=order_id, reservation_id=reservation_id
                ),
            ) from get_exc
        if reservation.get("status") != "CONFIRMED":
            set_inventory_status(order_id, "RELEASED", order_status="CANCELLED")
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "RESERVATION_NOT_ACTIVE",
                    "message": "Inventory reservation is no longer active",
                    "order_id": order_id,
                },
            ) from exc
        confirmation = reservation
    except InventoryUnavailable as exc:
        try:
            reservation = inventory_client.get_reservation(reservation_id)
        except (InventoryUnavailable, InventoryClientError):
            set_inventory_status(order_id, "CONFIRMATION_PENDING")
            raise HTTPException(
                status_code=503,
                detail=inventory_unavailable_detail(
                    order_id=order_id, reservation_id=reservation_id
                ),
            ) from exc
        if reservation.get("status") == "CONFIRMED" and reservation.get("order_id") == order_id:
            confirmation = reservation
        elif reservation.get("status") in {"RELEASED", "EXPIRED", "CANCELLED"}:
            set_inventory_status(order_id, "RELEASED", order_status="CANCELLED")
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "RESERVATION_NOT_ACTIVE",
                    "message": "Inventory reservation is no longer active",
                    "order_id": order_id,
                },
            ) from exc
        else:
            set_inventory_status(order_id, "CONFIRMATION_PENDING")
            raise HTTPException(
                status_code=503,
                detail=inventory_unavailable_detail(
                    order_id=order_id, reservation_id=reservation_id
                ),
            ) from exc

    if confirmation.get("order_id") != order_id:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "RESERVATION_ORDER_CONFLICT",
                "message": "Reservation is associated with another order",
            },
        )
    set_inventory_status(order_id, "CONFIRMED")
    updated = find_order_by_idempotency_key(str(order["idempotency_key"]))
    if updated is None:
        raise HTTPException(status_code=500, detail="Order disappeared after confirmation")
    event_key = ensure_order_created_event(order_id)
    updated["order_event_key"] = event_key
    return order_response(updated, event_key)


def complete_existing_order(order: dict[str, Any], request_hash: str) -> dict[str, Any]:
    if order["request_hash"] != request_hash:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "IDEMPOTENCY_KEY_REUSED",
                "message": "Idempotency-Key was already used with another order payload",
            },
        )
    if order["inventory_status"] == "CONFIRMED":
        event_key = ensure_order_created_event(int(order["id"]))
        order["order_event_key"] = event_key
        return order_response(order, event_key)
    if order["inventory_status"] in {"RESERVED", "CONFIRMATION_PENDING"}:
        return reconcile_confirmation(order)
    raise HTTPException(
        status_code=409,
        detail={
            "code": "ORDER_INVENTORY_NOT_CONFIRMABLE",
            "message": "The existing order no longer has confirmable inventory",
            "order_id": int(order["id"]),
        },
    )


def release_after_order_failure(reservation_id: str) -> None:
    try:
        inventory_client.release(reservation_id)
    except (InventoryClientError, InventoryUnavailable) as exc:
        log.error("Could not compensate inventory reservation %s: %s", reservation_id, exc)


@app.get("/health")
def healthcheck() -> dict[str, str]:
    return {
        "service": "order-service",
        "status": "healthy",
        "version": "1.1.0",
        "instance": os.getenv("INSTANCE_ID", socket.gethostname()),
    }


@app.post("/api/orders", status_code=status.HTTP_201_CREATED)
def create_order(
    response: Response,
    payload: CreateOrderRequest,
    idempotency_key: Annotated[
        str, Header(alias="Idempotency-Key", min_length=16, max_length=100)
    ],
) -> dict[str, Any]:
    normalized_items = normalize_items(payload.items)
    request_hash = order_request_hash(payload.user_id, normalized_items)
    existing = find_order_by_idempotency_key(idempotency_key)
    if existing is not None:
        response.status_code = status.HTTP_200_OK
        return complete_existing_order(existing, request_hash)

    order_snapshots: list[dict[str, Any]] = []
    subtotal = Decimal("0.00")
    for item in normalized_items:
        product = fetch_product_snapshot(item["product_id"])
        unit_price = Decimal(str(product["price"]))
        item_subtotal = unit_price * item["quantity"]
        order_snapshots.append(
            {
                "product_id": item["product_id"],
                "product_sku": product["sku"],
                "product_name": product["name"],
                "quantity": item["quantity"],
                "unit_price": unit_price,
                "subtotal": item_subtotal,
            }
        )
        subtotal += item_subtotal

    try:
        reservation = inventory_client.reserve(
            idempotency_key=idempotency_key,
            user_id=payload.user_id,
            items=normalized_items,
        )
    except InventoryClientError as exc:
        raise inventory_error_to_http(exc) from exc
    except InventoryUnavailable as exc:
        raise HTTPException(
            status_code=503, detail=inventory_unavailable_detail()
        ) from exc

    if reservation.get("status") != "ACTIVE":
        raise HTTPException(
            status_code=409,
            detail={
                "code": "RESERVATION_NOT_ACTIVE",
                "message": "Inventory reservation is not active",
            },
        )
    reservation_id = str(reservation["reservation_id"])
    tax = (subtotal * Decimal("0.18")).quantize(Decimal("0.01"))
    shipping_cost = Decimal("25.00")
    total_amount = subtotal + tax + shipping_cost

    conn = get_connection()
    order_id: int | None = None
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO orders
                    (user_id, idempotency_key, request_hash, inventory_reservation_id,
                     inventory_status, status, subtotal, tax, shipping_cost, total_amount)
                VALUES (%s, %s, %s, %s, 'RESERVED', 'PENDING', %s, %s, %s, %s)
                """,
                (
                    payload.user_id,
                    idempotency_key,
                    request_hash,
                    reservation_id,
                    str(subtotal),
                    str(tax),
                    str(shipping_cost),
                    str(total_amount),
                ),
            )
            order_id = int(cursor.lastrowid)
            for item in order_snapshots:
                cursor.execute(
                    """
                    INSERT INTO order_items
                        (order_id, product_id, product_sku, product_name,
                         quantity, unit_price, subtotal)
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
    except pymysql.IntegrityError as exc:
        conn.rollback()
        duplicate = find_order_by_idempotency_key(idempotency_key)
        if duplicate is not None:
            response.status_code = status.HTTP_200_OK
            return complete_existing_order(duplicate, request_hash)
        release_after_order_failure(reservation_id)
        raise HTTPException(status_code=500, detail="MySQL integrity error") from exc
    except Exception as exc:
        conn.rollback()
        release_after_order_failure(reservation_id)
        raise HTTPException(status_code=500, detail="MySQL error") from exc
    finally:
        conn.close()

    created = find_order_by_idempotency_key(idempotency_key)
    if created is None or order_id is None:
        release_after_order_failure(reservation_id)
        raise HTTPException(status_code=500, detail="Order was not persisted")
    result = reconcile_confirmation(created)
    response.status_code = status.HTTP_201_CREATED
    return result


@app.get("/api/orders/user/{user_id}")
def get_orders_by_user(user_id: str) -> Any:
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT * FROM orders WHERE user_id = %s ORDER BY created_at DESC",
                (user_id,),
            )
            return list(cursor.fetchall())
    finally:
        conn.close()


VALID_STATUSES = {"PENDING", "PAID", "SHIPPED", "CANCELLED"}
ALLOWED_TRANSITIONS = {
    "PENDING": {"PAID", "CANCELLED"},
    "PAID": {"SHIPPED", "CANCELLED"},
    "SHIPPED": set(),
    "CANCELLED": set(),
}


def cancel_order_inventory(order: dict[str, Any]) -> str:
    reservation_id = order.get("inventory_reservation_id")
    if not reservation_id:
        return str(order.get("inventory_status") or "RELEASED")
    try:
        reservation = inventory_client.get_reservation(str(reservation_id))
        reservation_status = reservation.get("status")
        if reservation_status == "CONFIRMED":
            inventory_client.cancel(
                str(reservation_id), int(order["id"]), "Order cancelled"
            )
            return "CANCELLED"
        if reservation_status == "ACTIVE":
            inventory_client.release(str(reservation_id))
            return "RELEASED"
        if reservation_status == "CANCELLED":
            return "CANCELLED"
        if reservation_status in {"RELEASED", "EXPIRED"}:
            return "RELEASED"
        raise HTTPException(
            status_code=409,
            detail={
                "code": "RESERVATION_NOT_CANCELLABLE",
                "message": "Inventory reservation cannot be cancelled",
            },
        )
    except InventoryClientError as exc:
        raise inventory_error_to_http(exc) from exc
    except InventoryUnavailable as exc:
        raise HTTPException(
            status_code=503,
            detail=inventory_unavailable_detail(
                order_id=int(order["id"]), reservation_id=str(reservation_id)
            ),
        ) from exc


@app.patch("/api/orders/{order_id}/status")
def update_order_status(order_id: int, payload: UpdateStatusRequest) -> dict[str, Any]:
    new_status = payload.status.upper()
    if new_status not in VALID_STATUSES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid status. Must be one of: {', '.join(sorted(VALID_STATUSES))}",
        )

    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT * FROM orders WHERE id = %s FOR UPDATE", (order_id,))
            order = cursor.fetchone()
            if not order:
                raise HTTPException(status_code=404, detail="Order not found")
            if order["status"] == new_status:
                conn.rollback()
                return {
                    "order_id": order_id,
                    "status": new_status,
                    "inventory_status": order.get("inventory_status"),
                    "event_published": False,
                    "event_key": None,
                }
            if new_status not in ALLOWED_TRANSITIONS[order["status"]]:
                raise HTTPException(
                    status_code=409,
                    detail={
                        "code": "INVALID_ORDER_TRANSITION",
                        "message": f"Cannot change order from {order['status']} to {new_status}",
                    },
                )

            inventory_status = order.get("inventory_status")
            if new_status == "CANCELLED":
                inventory_status = cancel_order_inventory(order)
            cursor.execute(
                "UPDATE orders SET status = %s, inventory_status = %s WHERE id = %s",
                (new_status, inventory_status, order_id),
            )
        conn.commit()
    except HTTPException:
        conn.rollback()
        raise
    except Exception as exc:
        conn.rollback()
        raise HTTPException(status_code=500, detail="MySQL error") from exc
    finally:
        conn.close()

    event_key = publish_order_status_changed_event(order, new_status)
    return {
        "order_id": order_id,
        "status": new_status,
        "inventory_status": inventory_status,
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
            cursor.execute(
                "SELECT * FROM order_items WHERE order_id = %s ORDER BY id ASC",
                (order_id,),
            )
            items = cursor.fetchall()
    finally:
        conn.close()
    return {"order": order, "items": items}
