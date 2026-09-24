import io
import unittest
from datetime import datetime, timezone

import pyarrow as pa
import pyarrow.parquet as pq

from inventory_ingestor import INVENTORY_SCHEMA, build_inventory_records


class InventoryIngestorTests(unittest.TestCase):
    def test_snapshot_schema_and_derived_stock_fields(self):
        created_at = datetime(2026, 9, 20, 8, 0)
        updated_at = datetime(2026, 9, 23, 15, 0, tzinfo=timezone.utc)
        snapshot_at = datetime(2026, 9, 23, 16, 0, tzinfo=timezone.utc)
        records = build_inventory_records(
            [
                {
                    "product_id": 7,
                    "available_quantity": 12,
                    "reserved_quantity": 9,
                    "minimum_quantity": 3,
                    "version": 4,
                    "created_at": created_at,
                    "updated_at": updated_at,
                }
            ],
            snapshot_at,
        )

        self.assertEqual(records[0]["sellable_quantity"], 3)
        self.assertTrue(records[0]["low_stock"])
        self.assertEqual(records[0]["created_at"].tzinfo, timezone.utc)
        self.assertEqual(
            INVENTORY_SCHEMA.names,
            [
                "product_id",
                "available_quantity",
                "reserved_quantity",
                "sellable_quantity",
                "minimum_quantity",
                "low_stock",
                "version",
                "created_at",
                "updated_at",
                "snapshot_at",
            ],
        )
        self.assertEqual(INVENTORY_SCHEMA.field("low_stock").type, pa.bool_())
        self.assertEqual(INVENTORY_SCHEMA.field("snapshot_at").type.tz, "UTC")

        table = pa.Table.from_pylist(records, schema=INVENTORY_SCHEMA)
        buffer = io.BytesIO()
        pq.write_table(table, buffer)
        restored = pq.read_table(io.BytesIO(buffer.getvalue()))
        self.assertEqual(restored.schema, INVENTORY_SCHEMA)
        self.assertEqual(restored.to_pylist(), records)


if __name__ == "__main__":
    unittest.main()
