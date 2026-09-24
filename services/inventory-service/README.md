# Inventory Service

FastAPI service that owns physical stock, atomic reservations, confirmations,
releases, cancellations and expiration. It listens on port `8006`.

## Run

```bash
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8006
```

Configuration is listed in `.env.example`. `DATABASE_URL` can replace the
individual `POSTGRES_*` values. API documentation is served at
`/inventory/docs`; the OpenAPI document is at `/inventory/openapi.json`.

## Test

Unit tests do not need external services:

```bash
python -m unittest discover -s tests -v
```

PostgreSQL integration tests are opt-in and use an isolated temporary schema:

```bash
INVENTORY_TEST_DATABASE_URL=postgresql://user:password@localhost:5432/database \
  python -m unittest tests.test_repository_integration -v
```

The test drops only the randomly named schema it created.

## Inventory events

Every successful stock mutation publishes its domain event after the
PostgreSQL transaction commits. Objects are written under:

```text
raw/events/inventory/year=YYYY/month=MM/day=DD/
```

The service emits `STOCK_ADJUSTED`, `STOCK_RESERVED`, `STOCK_CONFIRMED`,
`STOCK_RELEASED`, `RESERVATION_EXPIRED`, `STOCK_RESTORED` and
`LOW_STOCK_DETECTED`. An idempotent replay that does not apply a new transition
does not publish another event.

Mutation responses include `event_published`, `event_key` and `event_keys`.
An S3 failure is reported as `event_published: false` but never rolls back the
committed inventory change. This MVP intentionally has no transactional
outbox, so a failed publication is logged for operational follow-up.

Configure `S3_BUCKET`, `S3_EVENTS_PREFIX`, `AWS_DEFAULT_REGION` and, for local
development only, `S3_ENDPOINT_URL` and static AWS credentials. AWS deployments
use the instance role.
