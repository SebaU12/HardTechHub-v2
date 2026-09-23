import io
import os
import re
import sys

import pyarrow.parquet as pq

from common.s3_writer import get_s3_client


EXPECTED_COLUMNS = {
    "products": {"id", "sku", "price", "category", "brand", "snapshot_at"},
    "orders": {"id", "user_id", "status", "total_amount", "snapshot_at"},
    "order_items": {"id", "order_id", "product_id", "subtotal", "snapshot_at"},
    "users": {"user_id", "roles", "currency", "theme", "created_at", "snapshot_at"},
}
PARTITION_PATTERN = re.compile(r"/year=\d{4}/month=\d{2}/day=\d{2}/")


def main() -> None:
    client = get_s3_client()
    bucket = os.getenv("S3_BUCKET", "hardtech-datalake")
    requested = sys.argv[1:] or list(EXPECTED_COLUMNS)
    unknown = set(requested).difference(EXPECTED_COLUMNS)
    if unknown:
        raise RuntimeError(f"Unknown datasets: {sorted(unknown)}")

    for dataset in requested:
        required_columns = EXPECTED_COLUMNS[dataset]
        prefix = f"processed/snapshots/{dataset}/"
        response = client.list_objects_v2(Bucket=bucket, Prefix=prefix)
        objects = sorted(response.get("Contents", []), key=lambda item: item["LastModified"])
        if not objects:
            raise RuntimeError(f"No Parquet object found for {dataset}")

        key = objects[-1]["Key"]
        if not PARTITION_PATTERN.search(key):
            raise RuntimeError(f"Object is not date partitioned: {key}")
        body = client.get_object(Bucket=bucket, Key=key)["Body"].read()
        table = pq.read_table(io.BytesIO(body))
        missing = required_columns.difference(table.column_names)
        if missing:
            raise RuntimeError(f"{dataset} is missing columns: {sorted(missing)}")
        if dataset == "users" and {"email", "password_hash"}.intersection(table.column_names):
            raise RuntimeError("users snapshot contains sensitive columns")
        print(f"OK dataset={dataset} rows={table.num_rows} key={key}")


if __name__ == "__main__":
    main()
