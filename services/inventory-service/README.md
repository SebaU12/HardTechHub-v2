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
