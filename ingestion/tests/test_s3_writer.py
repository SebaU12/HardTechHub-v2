import io
import gc
import os
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

import pyarrow as pa
import pyarrow.parquet as pq

from common.s3_writer import get_s3_client, snapshot_key, upload_parquet


class CapturingS3Client:
    def put_object(self, **kwargs):
        self.request = kwargs


class S3WriterTests(unittest.TestCase):
    def test_aws_client_uses_instance_role_when_static_credentials_are_absent(self):
        with (
            patch.dict(os.environ, {"AWS_DEFAULT_REGION": "us-east-1"}, clear=True),
            patch("common.s3_writer.boto3.client") as boto_client,
        ):
            get_s3_client()

        boto_client.assert_called_once_with(
            "s3",
            endpoint_url=None,
            region_name="us-east-1",
            aws_access_key_id=None,
            aws_secret_access_key=None,
        )

    def test_local_client_uses_configured_endpoint_and_credentials(self):
        environment = {
            "S3_ENDPOINT_URL": "http://localstack:4566",
            "AWS_DEFAULT_REGION": "us-east-1",
            "AWS_ACCESS_KEY_ID": "test",
            "AWS_SECRET_ACCESS_KEY": "test",
        }
        with (
            patch.dict(os.environ, environment, clear=True),
            patch("common.s3_writer.boto3.client") as boto_client,
        ):
            get_s3_client()

        boto_client.assert_called_once_with(
            "s3",
            endpoint_url="http://localstack:4566",
            region_name="us-east-1",
            aws_access_key_id="test",
            aws_secret_access_key="test",
        )

    def test_snapshot_keys_are_partitioned_and_unique(self):
        snapshot_at = datetime(2026, 9, 23, 15, 30, tzinfo=timezone.utc)
        first = snapshot_key("/processed/snapshots/test/", "test", snapshot_at)
        second = snapshot_key("/processed/snapshots/test/", "test", snapshot_at)
        self.assertRegex(
            first,
            r"^processed/snapshots/test/year=2026/month=09/day=23/test_153000_[0-9a-f]{8}\.parquet$",
        )
        self.assertNotEqual(first, second)

    def test_upload_produces_readable_parquet_and_metadata(self):
        client = CapturingS3Client()
        schema = pa.schema(
            [
                pa.field("id", pa.int64(), nullable=False),
                pa.field("name", pa.string(), nullable=False),
            ]
        )
        with patch("common.s3_writer.get_s3_client", return_value=client):
            key = upload_parquet(
                [{"id": 1, "name": "demo"}],
                schema=schema,
                prefix="processed/snapshots/test/",
                dataset="test",
                snapshot_at=datetime(2026, 9, 23, tzinfo=timezone.utc),
            )

        parquet_file = pq.ParquetFile(io.BytesIO(client.request["Body"]))
        table = parquet_file.read(use_threads=False)
        self.assertEqual(table.to_pylist(), [{"id": 1, "name": "demo"}])
        self.assertEqual(client.request["Metadata"]["row-count"], "1")
        self.assertEqual(client.request["ContentType"], "application/vnd.apache.parquet")
        self.assertEqual(client.request["Key"], key)

        # Libera explícitamente los objetos nativos de Arrow antes de que termine
        # el intérprete. Esto evita un fallo de finalización observado en builds
        # Docker con algunas combinaciones de PyArrow y glibc.
        del table
        del parquet_file
        gc.collect()


if __name__ == "__main__":
    unittest.main()
