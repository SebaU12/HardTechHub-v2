import logging
import os
import time
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import boto3
from botocore.exceptions import BotoCoreError, ClientError


log = logging.getLogger("analytics.athena")

QUERY_FILES = {
    "event_count": "01_event_count_by_type.sql",
    "top_products": "02_top_five_viewed_products.sql",
    "sales_summary": "03_sales_summary.sql",
    "sales_by_category": "04_sales_by_category.sql",
    "product_conversion": "05_high_views_low_sales.sql",
    "compatibility_failures": "06_most_failed_compatibility_rules.sql",
    "compatibility_summary": "07_compatible_build_rate.sql",
    "user_registrations": "08_user_registrations_by_day.sql",
    "funnel": "09_view_compatibility_order_funnel.sql",
}


class AthenaQueryError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        execution_id: str | None = None,
        status_code: int = 502,
    ) -> None:
        super().__init__(message)
        self.execution_id = execution_id
        self.status_code = status_code


@dataclass(frozen=True)
class AthenaQueryResult:
    rows: list[dict[str, Any]]
    execution_id: str
    duration_ms: int


def get_athena_client() -> Any:
    return boto3.client(
        "athena",
        endpoint_url=os.getenv("ATHENA_ENDPOINT_URL") or None,
        region_name=os.getenv("AWS_DEFAULT_REGION", "us-east-1"),
    )


def get_queries_dir() -> Path:
    configured = os.getenv("ATHENA_QUERIES_DIR")
    if configured:
        return Path(configured).resolve()

    module_path = Path(__file__).resolve()
    candidates = [
        module_path.parents[1] / "queries",
        module_path.parents[3] / "infrastructure" / "athena" / "queries",
    ]
    return next((path for path in candidates if path.is_dir()), candidates[0])


def load_named_query(query_name: str) -> str:
    filename = QUERY_FILES.get(query_name)
    if filename is None:
        raise ValueError(f"Unknown analytical query: {query_name}")

    try:
        return (get_queries_dir() / filename).read_text(encoding="utf-8")
    except OSError as exc:
        raise AthenaQueryError(f"Analytical query is unavailable: {query_name}") from exc


def get_float_setting(name: str, default: str) -> float:
    try:
        value = float(os.getenv(name, default))
    except ValueError as exc:
        raise AthenaQueryError(
            f"Invalid Athena configuration: {name}",
            status_code=500,
        ) from exc
    if value < 0:
        raise AthenaQueryError(
            f"Invalid Athena configuration: {name}",
            status_code=500,
        )
    return value


def convert_athena_value(raw_value: str | None, athena_type: str) -> Any:
    if raw_value is None:
        return None
    normalized_type = athena_type.lower()
    if normalized_type in {"tinyint", "smallint", "integer", "int", "bigint"}:
        return int(raw_value)
    if normalized_type in {"real", "float", "double"}:
        return float(raw_value)
    if normalized_type == "boolean":
        return raw_value.lower() == "true"
    if normalized_type.startswith("decimal"):
        try:
            return str(Decimal(raw_value))
        except InvalidOperation:
            return raw_value
    return raw_value


def _data_value(cell: dict[str, str] | None) -> str | None:
    return cell.get("VarCharValue") if cell else None


def fetch_all_rows(client: Any, execution_id: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    next_token: str | None = None
    first_page = True
    columns: list[dict[str, str]] = []

    while True:
        request: dict[str, Any] = {"QueryExecutionId": execution_id}
        if next_token:
            request["NextToken"] = next_token
        response = client.get_query_results(**request)
        if not columns:
            columns = response["ResultSet"]["ResultSetMetadata"]["ColumnInfo"]
        page_rows = response["ResultSet"].get("Rows", [])
        if first_page and page_rows:
            page_rows = page_rows[1:]

        for row in page_rows:
            cells = row.get("Data", [])
            rows.append(
                {
                    column["Name"]: convert_athena_value(
                        _data_value(cells[index]) if index < len(cells) else None,
                        column["Type"],
                    )
                    for index, column in enumerate(columns)
                }
            )

        next_token = response.get("NextToken")
        first_page = False
        if not next_token:
            return rows


def execute_named_query(query_name: str, client: Any | None = None) -> AthenaQueryResult:
    athena = client or get_athena_client()
    query = load_named_query(query_name)
    database = os.getenv("ATHENA_DATABASE", "hardtech_analytics")
    workgroup = os.getenv("ATHENA_WORKGROUP", "hardtech-workgroup")
    output_location = os.getenv(
        "ATHENA_OUTPUT_LOCATION",
        "s3://hardtech-datalake/athena-results/",
    )
    timeout_seconds = get_float_setting("ATHENA_QUERY_TIMEOUT_SECONDS", "30")
    poll_seconds = get_float_setting("ATHENA_POLL_INTERVAL_SECONDS", "0.5")
    started_at = time.monotonic()
    execution_id: str | None = None

    try:
        response = athena.start_query_execution(
            QueryString=query,
            QueryExecutionContext={"Database": database},
            WorkGroup=workgroup,
            ResultConfiguration={"OutputLocation": output_location},
        )
        execution_id = response["QueryExecutionId"]

        while True:
            execution = athena.get_query_execution(QueryExecutionId=execution_id)["QueryExecution"]
            status = execution["Status"]
            state = status["State"]
            if state == "SUCCEEDED":
                break
            if state in {"FAILED", "CANCELLED"}:
                reason = status.get("StateChangeReason", "No reason supplied")
                raise AthenaQueryError(
                    f"Athena query {state.lower()}: {reason}",
                    execution_id=execution_id,
                )
            if state not in {"QUEUED", "RUNNING"}:
                raise AthenaQueryError(
                    f"Athena returned an unexpected state: {state}",
                    execution_id=execution_id,
                )
            if time.monotonic() - started_at >= timeout_seconds:
                athena.stop_query_execution(QueryExecutionId=execution_id)
                raise AthenaQueryError(
                    "Athena query timed out",
                    execution_id=execution_id,
                    status_code=504,
                )
            time.sleep(poll_seconds)

        rows = fetch_all_rows(athena, execution_id)
    except AthenaQueryError:
        raise
    except (ClientError, BotoCoreError, KeyError, ValueError) as exc:
        log.exception("Athena request failed query=%s execution_id=%s", query_name, execution_id)
        raise AthenaQueryError("Athena request failed", execution_id=execution_id) from exc

    duration_ms = round((time.monotonic() - started_at) * 1000)
    log.info(
        "Athena query completed query=%s execution_id=%s duration_ms=%d rows=%d",
        query_name,
        execution_id,
        duration_ms,
        len(rows),
    )
    return AthenaQueryResult(rows=rows, execution_id=execution_id, duration_ms=duration_ms)
