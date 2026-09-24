import json
import logging
import os
import socket
from collections import Counter
from typing import Any

import boto3
from botocore.exceptions import BotoCoreError, ClientError
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse

from app.athena_backend import AthenaQueryError, AthenaQueryResult, execute_named_query


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("analytics")


def get_backend() -> str:
    backend = os.getenv("ANALYTICS_BACKEND", "s3").strip().lower()
    if backend not in {"s3", "athena"}:
        raise HTTPException(status_code=500, detail="Invalid analytics backend configuration")
    return backend


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


def get_bucket_name() -> str:
    return os.getenv("S3_BUCKET", "hardtech-datalake")


def get_events_prefix() -> str:
    return os.getenv("S3_EVENTS_PREFIX", "raw/events/")


def list_event_objects() -> list[str]:
    s3_client = get_s3_client()
    keys: list[str] = []
    try:
        paginator = s3_client.get_paginator("list_objects_v2")
        for page in paginator.paginate(
            Bucket=get_bucket_name(),
            Prefix=get_events_prefix(),
        ):
            keys.extend(
                obj["Key"]
                for obj in page.get("Contents", [])
                if obj["Key"].endswith(".json")
            )
    except (ClientError, BotoCoreError) as exc:
        raise HTTPException(status_code=502, detail="S3 analytics backend unavailable") from exc
    return keys


def load_events() -> list[dict[str, Any]]:
    s3_client = get_s3_client()
    events: list[dict[str, Any]] = []
    for key in list_event_objects():
        try:
            response = s3_client.get_object(Bucket=get_bucket_name(), Key=key)
        except (ClientError, BotoCoreError) as exc:
            raise HTTPException(status_code=502, detail="S3 analytics backend unavailable") from exc

        payload = response["Body"].read().decode("utf-8").strip()
        if not payload:
            continue
        try:
            parsed = json.loads(payload)
        except json.JSONDecodeError:
            try:
                events.extend(json.loads(line) for line in payload.splitlines() if line.strip())
            except json.JSONDecodeError as exc:
                raise HTTPException(status_code=500, detail="Invalid event JSON in data lake") from exc
        else:
            events.extend(parsed if isinstance(parsed, list) else [parsed])
    return events


def run_athena(query_name: str) -> AthenaQueryResult:
    try:
        return execute_named_query(query_name)
    except AthenaQueryError as exc:
        log.warning(
            "Athena query error query=%s execution_id=%s error=%s",
            query_name,
            exc.execution_id,
            exc,
        )
        detail: dict[str, Any] = {"message": str(exc)}
        if exc.execution_id:
            detail["query_execution_id"] = exc.execution_id
        raise HTTPException(status_code=exc.status_code, detail=detail) from exc


def athena_response(result: AthenaQueryResult, key: str, value: Any) -> dict[str, Any]:
    return {
        key: value,
        "backend": "athena",
        "query_execution_id": result.execution_id,
        "duration_ms": result.duration_ms,
    }


def require_athena(query_name: str) -> AthenaQueryResult:
    if get_backend() != "athena":
        raise HTTPException(
            status_code=503,
            detail="This analytical endpoint requires ANALYTICS_BACKEND=athena",
        )
    return run_athena(query_name)


def documented_response(example: dict[str, Any]) -> dict[int | str, dict[str, Any]]:
    return {200: {"content": {"application/json": {"example": example}}}}


def _servers() -> list[dict[str, str]]:
    base = os.getenv("API_BASE_URL", "").strip()
    return [{"url": base, "description": "API Gateway / Local"}] if base else []


app = FastAPI(
    title="Analytics Service",
    version="2.0.0",
    description="Analítica de HardTech Hub con backend S3 local o Amazon Athena.",
    docs_url=None,
    openapi_url="/analytics/openapi.json",
    servers=_servers(),
)


@app.get("/analytics/docs", include_in_schema=False)
def analytics_docs() -> HTMLResponse:
    # Embed the specification so browser privacy filters cannot block the
    # secondary fetch merely because its URL contains the word "analytics".
    specification = json.dumps(app.openapi(), ensure_ascii=False).replace("</", "<\\/")
    return HTMLResponse(
        f"""<!DOCTYPE html>
<html>
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Analytics Service - Swagger UI</title>
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui.css">
  </head>
  <body>
    <div id="swagger-ui"></div>
    <script src="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui-bundle.js"></script>
    <script>
      SwaggerUIBundle({{
        spec: {specification},
        dom_id: "#swagger-ui",
        deepLinking: true,
        docExpansion: "list",
        presets: [SwaggerUIBundle.presets.apis],
        layout: "BaseLayout"
      }});
    </script>
  </body>
</html>"""
    )


@app.get("/health", summary="Estado del servicio")
def healthcheck() -> dict[str, str]:
    return {
        "service": "analytics-service",
        "status": "healthy",
        "version": "2.0.0",
        "backend": get_backend(),
        "instance": os.getenv("INSTANCE_ID") or socket.gethostname(),
    }


@app.get(
    "/api/analytics/events/count",
    summary="Contar eventos por tipo",
    responses=documented_response(
        {"total_events": 42, "by_type": {"PRODUCT_VIEW": 20}, "backend": "athena"}
    ),
)
def count_events() -> dict[str, Any]:
    if get_backend() == "s3":
        events = load_events()
        event_types = Counter(event.get("event_type", "UNKNOWN") for event in events)
        return {
            "total_events": len(events),
            "by_type": dict(event_types),
            "prefix": get_events_prefix(),
            "backend": "s3",
        }

    result = run_athena("event_count")
    by_type = {str(row["event_type"]): int(row["event_count"]) for row in result.rows}
    return athena_response(result, "by_type", by_type) | {"total_events": sum(by_type.values())}


@app.get(
    "/api/analytics/top-products",
    summary="Obtener los cinco productos con más vistas",
    responses=documented_response(
        {"top_products": [{"product_id": 1, "views": 15}], "backend": "athena"}
    ),
)
def top_products() -> dict[str, Any]:
    if get_backend() == "s3":
        events = load_events()
        product_views = Counter(
            str(event["product_id"])
            for event in events
            if event.get("event_type") == "PRODUCT_VIEW" and event.get("product_id") is not None
        )
        top = [
            {"product_id": product_id, "views": views}
            for product_id, views in product_views.most_common(5)
        ]
        return {"top_products": top, "backend": "s3"}

    result = run_athena("top_products")
    top = [
        {"product_id": row["product_id"], "views": row["view_count"]}
        for row in result.rows
    ]
    return athena_response(result, "top_products", top)


@app.get(
    "/api/analytics/sales/summary",
    summary="Resumen general de ventas",
    responses=documented_response(
        {"sales_summary": {"order_count": 7, "gross_revenue": "9219.16"}, "backend": "athena"}
    ),
)
def sales_summary() -> dict[str, Any]:
    result = require_athena("sales_summary")
    return athena_response(result, "sales_summary", result.rows[0] if result.rows else {})


@app.get(
    "/api/analytics/sales/by-category",
    summary="Ventas agrupadas por categoría",
    responses=documented_response(
        {"categories": [{"category": "GPU", "units_sold": 3, "sales_amount": "9299.70"}], "backend": "athena"}
    ),
)
def sales_by_category() -> dict[str, Any]:
    result = require_athena("sales_by_category")
    return athena_response(result, "categories", result.rows)


@app.get(
    "/api/analytics/products/conversion",
    summary="Comparar vistas con unidades vendidas",
    responses=documented_response(
        {"products": [{"product_id": 3, "view_count": 30, "units_sold": 1}], "backend": "athena"}
    ),
)
def product_conversion() -> dict[str, Any]:
    result = require_athena("product_conversion")
    return athena_response(result, "products", result.rows)


@app.get(
    "/api/analytics/compatibility/failure-rules",
    summary="Reglas de compatibilidad con más fallos",
    responses=documented_response(
        {"failure_rules": [{"failed_rule": "PSU_POWER", "failure_count": 4}], "backend": "athena"}
    ),
)
def compatibility_failure_rules() -> dict[str, Any]:
    result = require_athena("compatibility_failures")
    return athena_response(result, "failure_rules", result.rows)


@app.get(
    "/api/analytics/compatibility/summary",
    summary="Tasa de builds compatibles",
    responses=documented_response(
        {"compatibility": {"checked_builds": 10, "compatible_rate_pct": 70.0}, "backend": "athena"}
    ),
)
def compatibility_summary() -> dict[str, Any]:
    result = require_athena("compatibility_summary")
    return athena_response(result, "compatibility", result.rows[0] if result.rows else {})


@app.get(
    "/api/analytics/users/registrations",
    summary="Registros de usuarios por día",
    responses=documented_response(
        {"registrations": [{"registration_day": "2026-09-23", "registered_users": 5}], "backend": "athena"}
    ),
)
def user_registrations() -> dict[str, Any]:
    result = require_athena("user_registrations")
    return athena_response(result, "registrations", result.rows)


@app.get(
    "/api/analytics/funnel",
    summary="Embudo de vista, compatibilidad y orden",
    responses=documented_response(
        {"funnel": {"users_with_view": 20, "users_with_order": 4}, "backend": "athena"}
    ),
)
def funnel() -> dict[str, Any]:
    result = require_athena("funnel")
    return athena_response(result, "funnel", result.rows[0] if result.rows else {})


@app.get(
    "/api/analytics/inventory/summary",
    summary="Resumen del snapshot de inventario más reciente",
    responses=documented_response(
        {
            "inventory_summary": {
                "total_products": 20000,
                "physical_units": 400000,
                "reserved_units": 125,
                "sellable_units": 399875,
                "low_stock_products": 18,
                "snapshot_at": "2026-09-23 16:00:00.000",
            },
            "backend": "athena",
            "query_execution_id": "query-123",
            "duration_ms": 42,
        }
    ),
)
def inventory_summary() -> dict[str, Any]:
    result = require_athena("inventory_summary")
    return athena_response(
        result,
        "inventory_summary",
        result.rows[0] if result.rows else {},
    )


@app.get(
    "/api/analytics/inventory/low-stock",
    summary="Productos con stock bajo en el snapshot más reciente",
    responses=documented_response(
        {
            "low_stock": [
                {
                    "product_id": 7,
                    "available_quantity": 3,
                    "reserved_quantity": 1,
                    "sellable_quantity": 2,
                    "minimum_quantity": 2,
                }
            ],
            "backend": "athena",
            "query_execution_id": "query-456",
            "duration_ms": 38,
        }
    ),
)
def inventory_low_stock() -> dict[str, Any]:
    result = require_athena("inventory_low_stock")
    return athena_response(result, "low_stock", result.rows)
