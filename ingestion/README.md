# Data lake ingestors

Each ingestor extracts an operational dataset and writes a complete Parquet
snapshot partitioned by `year`, `month` and `day`.

## Inventory

`inventory_ingestor.py` reads `hardtech_inventory.inventory_stock` with the
read-only `hardtech_reader` account. It derives `sellable_quantity` and
`low_stock` before writing to
`processed/snapshots/inventory/year=YYYY/month=MM/day=DD/`.

Run one snapshot:

```bash
RUN_ONCE=true python inventory_ingestor.py
```

Run continuously, every five minutes:

```bash
RUN_ONCE=false SNAPSHOT_INTERVAL_SECONDS=300 python inventory_ingestor.py
```

Connection variables are `POSTGRES_HOST`, `POSTGRES_PORT`, `POSTGRES_DB`,
`POSTGRES_USER` and `POSTGRES_PASSWORD`. S3 uses `S3_BUCKET`, optional
`S3_ENDPOINT_URL`, AWS credentials/instance role and `S3_OUTPUT_PREFIX`.
