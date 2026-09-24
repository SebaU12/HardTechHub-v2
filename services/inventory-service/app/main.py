from __future__ import annotations

import asyncio
import json
import logging
import os
import socket
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, AsyncIterator, Annotated
from urllib.error import HTTPError, URLError
from urllib.request import urlopen
from uuid import UUID

from fastapi import FastAPI, Header, Query, Request, Response, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from psycopg import Error as PsycopgError

from app.database import database
from app.errors import DatabaseUnavailable, InventoryError
from app.events import build_event, publish_events
from app.models import (
    AdjustmentRequest,
    CancelReservationRequest,
    ConfirmReservationRequest,
    CreateReservationRequest,
    LowStockResponse,
    ReservationResponse,
    StockResponse,
)
from app.repository import InventoryRepository, normalize_items


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        data: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "service": "inventory-service",
            "message": record.getMessage(),
        }
        for field in ("operation", "product_id", "reservation_id", "order_id", "status"):
            if hasattr(record, field):
                data[field] = getattr(record, field)
        return json.dumps(data, default=str, separators=(",", ":"))


def configure_logging() -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(os.getenv("LOG_LEVEL", "INFO").upper())


configure_logging()
log = logging.getLogger("inventory-service")
repository = InventoryRepository(database)


def _servers() -> list[dict[str, str]]:
    base = os.getenv("API_BASE_URL", "").strip()
    return [{"url": base, "description": "API Gateway / Local"}] if base else []


async def expiration_worker() -> None:
    interval = max(1, int(os.getenv("EXPIRATION_INTERVAL_SECONDS", "30")))
    batch_size = max(1, int(os.getenv("EXPIRATION_BATCH_SIZE", "50")))
    while True:
        await asyncio.sleep(interval)
        try:
            expired = await asyncio.to_thread(repository.expire_reservations, batch_size)
            for item in expired:
                reservation = item["reservation"]
                event = reservation_event("RESERVATION_EXPIRED", reservation)
                published, keys = await asyncio.to_thread(publish_events, [event])
                log.info(
                    "Reservation expired event_published=%s event_key=%s",
                    published,
                    keys[0] if keys else None,
                    extra={
                        "operation": "expire",
                        "reservation_id": str(reservation["reservation_id"]),
                    },
                )
        except InventoryError as exc:
            log.error("Expiration pass failed: %s", exc.code, extra={"operation": "expire"})
        except Exception:
            log.exception("Unexpected expiration failure", extra={"operation": "expire"})


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    task: asyncio.Task[None] | None = None
    if os.getenv("EXPIRATION_WORKER_ENABLED", "true").lower() in {"1", "true", "yes"}:
        task = asyncio.create_task(expiration_worker())
    yield
    if task is not None:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
    database.close()


app = FastAPI(
    title="Inventory Service",
    description="Stock, atomic reservations and inventory movement API for HardTech.",
    version="1.0.0",
    docs_url="/inventory/docs",
    openapi_url="/inventory/openapi.json",
    servers=_servers(),
    lifespan=lifespan,
)


@app.exception_handler(InventoryError)
async def inventory_error_handler(_: Request, exc: InventoryError) -> JSONResponse:
    log.warning(
        "%s: %s",
        exc.code,
        exc.message,
        extra={"operation": "request_error", "status": exc.status_code},
    )
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.body()})


@app.exception_handler(PsycopgError)
async def database_error_handler(_: Request, exc: PsycopgError) -> JSONResponse:
    log.error("PostgreSQL operation failed: %s", type(exc).__name__)
    error = DatabaseUnavailable()
    return JSONResponse(status_code=error.status_code, content={"detail": error.body()})


@app.exception_handler(RequestValidationError)
async def validation_error_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
    errors = []
    for error in exc.errors():
        errors.append(
            {
                "field": ".".join(str(part) for part in error["loc"] if part != "body"),
                "message": error["msg"],
            }
        )
    return JSONResponse(
        status_code=422,
        content={
            "detail": {
                "code": "VALIDATION_ERROR",
                "message": "Request validation failed",
                "errors": errors,
            }
        },
    )


@app.middleware("http")
async def access_log(request: Request, call_next: Any) -> Any:
    response = await call_next(request)
    log.info(
        "%s %s",
        request.method,
        request.url.path,
        extra={"operation": "http_request", "status": response.status_code},
    )
    return response


def validate_catalog_product(product_id: int) -> None:
    base_url = os.getenv("CATALOG_SERVICE_URL", "http://catalog-service:8002").rstrip("/")
    last_error: Exception | None = None
    for _ in range(2):
        try:
            with urlopen(f"{base_url}/api/products/{product_id}", timeout=3) as response:
                if response.status == 200:
                    return
        except HTTPError as exc:
            if exc.code == 404:
                raise InventoryError(404, "PRODUCT_NOT_FOUND", "Catalog product was not found") from exc
            last_error = exc
        except (URLError, TimeoutError) as exc:
            last_error = exc
    raise InventoryError(503, "CATALOG_UNAVAILABLE", "Catalog Service is unavailable") from last_error


def reservation_event(
    event_type: str,
    reservation: dict[str, Any],
    *,
    order_id: int | None = None,
    reason: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "reservation_id": str(reservation["reservation_id"]),
        "status": reservation["status"],
        "expires_at": reservation["expires_at"].isoformat(),
        "items": reservation["items"],
    }
    if reason is not None:
        payload["reason"] = reason
    return build_event(
        event_type,
        payload,
        user_id=reservation.get("_user_id"),
        order_id=order_id if order_id is not None else reservation.get("order_id"),
    )


def low_stock_event(stock: dict[str, Any]) -> dict[str, Any]:
    return build_event(
        "LOW_STOCK_DETECTED",
        {
            "available_quantity": stock["available_quantity"],
            "reserved_quantity": stock["reserved_quantity"],
            "sellable_quantity": stock["sellable_quantity"],
            "minimum_quantity": stock["minimum_quantity"],
        },
        product_id=stock["product_id"],
    )


def with_publication(
    result: dict[str, Any], events: list[dict[str, Any]]
) -> dict[str, Any]:
    published, keys = publish_events(events)
    return result | {
        "event_published": published,
        "event_key": keys[0] if keys else None,
        "event_keys": keys,
    }


@app.get("/health", tags=["operations"])
def healthcheck() -> dict[str, str]:
    return {
        "service": "inventory-service",
        "status": "healthy",
        "version": "1.0.0",
        "instance": os.getenv("INSTANCE_ID", socket.gethostname()),
    }


@app.get(
    "/api/inventory/low-stock",
    response_model=LowStockResponse,
    tags=["stock"],
    summary="List products at or below their minimum sellable stock",
)
def low_stock(
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> dict[str, Any]:
    return {"items": repository.list_low_stock(limit, offset), "limit": limit, "offset": offset}


@app.get(
    "/api/inventory/reservations/{reservation_id}",
    response_model=ReservationResponse,
    tags=["reservations"],
)
def get_reservation(reservation_id: UUID) -> dict[str, Any]:
    return repository.get_reservation(reservation_id)


@app.get(
    "/api/inventory/{product_id}",
    response_model=StockResponse,
    tags=["stock"],
)
def get_stock(product_id: int) -> dict[str, Any]:
    if product_id <= 0:
        raise InventoryError(422, "VALIDATION_ERROR", "product_id must be greater than zero")
    return repository.get_stock(product_id)


@app.post(
    "/api/inventory/adjustments",
    response_model=StockResponse,
    tags=["stock"],
)
def adjust_stock(payload: AdjustmentRequest) -> dict[str, Any]:
    if not repository.stock_exists(payload.product_id):
        validate_catalog_product(payload.product_id)
    result, context = repository.adjust_stock(
        product_id=payload.product_id,
        quantity_delta=payload.quantity_delta,
        minimum_quantity=payload.minimum_quantity,
        reason=payload.reason.strip(),
    )
    log.info(
        "Stock adjusted",
        extra={"operation": "adjust", "product_id": payload.product_id},
    )
    events = [
        build_event(
            "STOCK_ADJUSTED",
            {
                "quantity_delta": context["quantity_delta"],
                "quantity_before": context["quantity_before"],
                "quantity_after": context["quantity_after"],
                "available_quantity": result["available_quantity"],
                "reserved_quantity": result["reserved_quantity"],
                "sellable_quantity": result["sellable_quantity"],
                "minimum_quantity": result["minimum_quantity"],
                "reason": context["reason"],
            },
            product_id=payload.product_id,
        )
    ]
    if context["became_low_stock"]:
        events.append(low_stock_event(result))
    return with_publication(result, events)


@app.post(
    "/api/inventory/reservations",
    response_model=ReservationResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["reservations"],
)
def create_reservation(
    response: Response,
    payload: CreateReservationRequest,
    idempotency_key: Annotated[
        str,
        Header(alias="Idempotency-Key", min_length=16, max_length=100),
    ],
) -> dict[str, Any]:
    items = normalize_items(payload.items)
    reservation, created, low_stock_products = repository.create_reservation(
        idempotency_key=idempotency_key,
        user_id=payload.user_id,
        items=items,
    )
    if not created:
        response.status_code = status.HTTP_200_OK
    log.info(
        "Reservation returned",
        extra={
            "operation": "reserve",
            "reservation_id": str(reservation["reservation_id"]),
            "status": reservation["status"],
        },
    )
    if not created:
        return reservation
    events = [reservation_event("STOCK_RESERVED", reservation)]
    events.extend(low_stock_event(stock) for stock in low_stock_products)
    return with_publication(reservation, events)


@app.post(
    "/api/inventory/reservations/{reservation_id}/confirm",
    response_model=ReservationResponse,
    tags=["reservations"],
)
def confirm_reservation(
    reservation_id: UUID, payload: ConfirmReservationRequest
) -> dict[str, Any]:
    result, changed = repository.confirm_reservation(reservation_id, payload.order_id)
    log.info(
        "Reservation confirmed",
        extra={
            "operation": "confirm",
            "reservation_id": str(reservation_id),
            "order_id": payload.order_id,
        },
    )
    if not changed:
        return result
    return with_publication(
        result,
        [reservation_event("STOCK_CONFIRMED", result, order_id=payload.order_id)],
    )


@app.delete(
    "/api/inventory/reservations/{reservation_id}",
    response_model=ReservationResponse,
    tags=["reservations"],
)
def release_reservation(reservation_id: UUID) -> dict[str, Any]:
    result, changed = repository.release_reservation(reservation_id)
    log.info(
        "Reservation released",
        extra={"operation": "release", "reservation_id": str(reservation_id)},
    )
    if not changed:
        return result
    return with_publication(result, [reservation_event("STOCK_RELEASED", result)])


@app.post(
    "/api/inventory/reservations/{reservation_id}/cancel",
    response_model=ReservationResponse,
    tags=["reservations"],
)
def cancel_reservation(
    reservation_id: UUID, payload: CancelReservationRequest
) -> dict[str, Any]:
    result, changed = repository.cancel_reservation(
        reservation_id, payload.order_id, payload.reason.strip()
    )
    log.info(
        "Confirmed sale cancelled",
        extra={
            "operation": "cancel",
            "reservation_id": str(reservation_id),
            "order_id": payload.order_id,
        },
    )
    if not changed:
        return result
    return with_publication(
        result,
        [
            reservation_event(
                "STOCK_RESTORED",
                result,
                order_id=payload.order_id,
                reason=payload.reason,
            )
        ],
    )
