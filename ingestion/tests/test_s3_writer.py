import io
import gc
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

import pyarrow as pa
import pyarrow.parquet as pq

from common.s3_writer import snapshot_key, upload_parquet


class CapturingS3Client:
    def put_object(self, **kwargs):
        self.request = kwargs


class S3WriterTests(unittest.TestCase):
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
