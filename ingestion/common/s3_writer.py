import io
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Any

import boto3
import pyarrow as pa
import pyarrow.parquet as pq


log = logging.getLogger("s3-writer")


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def get_s3_client() -> Any:
    endpoint = os.getenv("S3_ENDPOINT_URL")
    return boto3.client(
        "s3",
        endpoint_url=endpoint or None,
        region_name=os.getenv("AWS_DEFAULT_REGION", "us-east-1"),
        aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
        aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
    )


def snapshot_key(prefix: str, dataset: str, snapshot_at: datetime) -> str:
    normalized_prefix = prefix.strip("/")
    suffix = f"{snapshot_at.strftime('%H%M%S')}_{uuid.uuid4().hex[:8]}"
    return (
        f"{normalized_prefix}/year={snapshot_at.year}/month={snapshot_at.month:02d}"
        f"/day={snapshot_at.day:02d}/{dataset}_{suffix}.parquet"
    )


def upload_parquet(
    records: list[dict[str, Any]],
    *,
    schema: pa.Schema,
    prefix: str,
    dataset: str,
    snapshot_at: datetime,
) -> str:
    table = pa.Table.from_pylist(records, schema=schema)
    buffer = io.BytesIO()
    pq.write_table(table, buffer, compression="snappy")
    key = snapshot_key(prefix, dataset, snapshot_at)

    get_s3_client().put_object(
        Bucket=os.getenv("S3_BUCKET", "hardtech-datalake"),
        Key=key,
        Body=buffer.getvalue(),
        ContentType="application/vnd.apache.parquet",
        Metadata={
            "dataset": dataset,
            "row-count": str(table.num_rows),
            "snapshot-at": snapshot_at.isoformat(),
        },
    )
    log.info(
        "Uploaded dataset=%s rows=%d columns=%d to s3://%s/%s",
        dataset,
        table.num_rows,
        table.num_columns,
        os.getenv("S3_BUCKET", "hardtech-datalake"),
        key,
    )
    return key
