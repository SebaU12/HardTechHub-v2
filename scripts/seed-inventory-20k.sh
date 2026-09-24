#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
cd "$ROOT_DIR"

SEED_COUNT=20000
FORCE_SEED=false

for argument in "$@"; do
  case "$argument" in
    --force) FORCE_SEED=true ;;
    *[!0-9]*|'') echo "Uso: $0 [cantidad>=20000] [--force]" >&2; exit 2 ;;
    *) SEED_COUNT=$argument ;;
  esac
done

if (( SEED_COUNT < 20000 )); then
  echo "La cantidad mínima permitida es 20000" >&2
  exit 2
fi

POSTGRES_ADMIN_USER=${POSTGRES_USER:-hardtech}
POSTGRES_ADMIN_PASSWORD=${POSTGRES_PASSWORD:-hardtech}
CATALOG_DATABASE=${POSTGRES_DB:-hardtech_catalog}
INVENTORY_DATABASE=${INVENTORY_DB:-hardtech_inventory}

docker compose up -d --wait postgres

docker compose exec -T postgres psql \
  --username "$POSTGRES_ADMIN_USER" \
  --dbname "$INVENTORY_DATABASE" \
  --set ON_ERROR_STOP=1 \
  --set catalog_db="$CATALOG_DATABASE" \
  --set postgres_user="$POSTGRES_ADMIN_USER" \
  --set postgres_password="$POSTGRES_ADMIN_PASSWORD" \
  --set seed_count="$SEED_COUNT" \
  --set force_seed="$FORCE_SEED" <<'SQL'
BEGIN;

CREATE TEMP TABLE inventory_seed_products (
    product_id BIGINT PRIMARY KEY,
    sku TEXT NOT NULL,
    target_quantity INTEGER NOT NULL,
    target_minimum INTEGER NOT NULL
) ON COMMIT DROP;

INSERT INTO inventory_seed_products (product_id, sku, target_quantity, target_minimum)
SELECT
    product_id,
    sku,
    50 + (product_id % 151)::integer,
    10 + (product_id % 11)::integer
FROM dblink(
    format(
        'dbname=%L user=%L password=%L',
        :'catalog_db',
        :'postgres_user',
        :'postgres_password'
    ),
    format(
        'SELECT id::bigint, sku::text FROM products WHERE is_active = true AND (sku NOT LIKE ''FAKE-SEED-%%'' OR id IN (SELECT id FROM products WHERE sku LIKE ''FAKE-SEED-%%'' ORDER BY id LIMIT %s)) ORDER BY id',
        :'seed_count'
    )
) AS catalog_products(product_id BIGINT, sku TEXT);

CREATE TEMP TABLE inventory_seed_before ON COMMIT DROP AS
SELECT
    seed.product_id,
    seed.target_quantity,
    seed.target_minimum,
    stock.available_quantity AS quantity_before
FROM inventory_seed_products seed
LEFT JOIN inventory_stock stock ON stock.product_id = seed.product_id;

INSERT INTO inventory_stock (
    product_id,
    available_quantity,
    reserved_quantity,
    minimum_quantity,
    version
)
SELECT product_id, target_quantity, 0, target_minimum, 0
FROM inventory_seed_products
ON CONFLICT (product_id) DO UPDATE
SET
    available_quantity = GREATEST(EXCLUDED.available_quantity, inventory_stock.reserved_quantity),
    minimum_quantity = EXCLUDED.minimum_quantity,
    version = inventory_stock.version + 1
WHERE :'force_seed'::boolean;

INSERT INTO stock_movements (
    product_id,
    movement_type,
    quantity,
    quantity_before,
    quantity_after,
    reason
)
SELECT
    before.product_id,
    CASE WHEN before.quantity_before IS NULL THEN 'INITIAL_STOCK' ELSE 'MANUAL_ADJUSTMENT' END,
    stock.available_quantity - COALESCE(before.quantity_before, 0),
    COALESCE(before.quantity_before, 0),
    stock.available_quantity,
    CASE
        WHEN before.quantity_before IS NULL THEN 'Seed inicial reproducible'
        ELSE 'Reinicio forzado del seed reproducible'
    END
FROM inventory_seed_before before
JOIN inventory_stock stock ON stock.product_id = before.product_id
WHERE
    before.quantity_before IS NULL
    OR (
        :'force_seed'::boolean
        AND stock.available_quantity <> before.quantity_before
    );

COMMIT;
SQL

IFS='|' read -r fake_count total_count movement_count < <(
  docker compose exec -T postgres psql \
    --username "$POSTGRES_ADMIN_USER" \
    --dbname "$INVENTORY_DATABASE" \
    --tuples-only --no-align --field-separator='|' \
    --set catalog_db="$CATALOG_DATABASE" \
    --set postgres_user="$POSTGRES_ADMIN_USER" \
    --set postgres_password="$POSTGRES_ADMIN_PASSWORD" <<'SQL'
WITH fake_products AS (
  SELECT product_id
  FROM dblink(
    format(
      'dbname=%L user=%L password=%L',
      :'catalog_db',
      :'postgres_user',
      :'postgres_password'
    ),
    'SELECT id::bigint FROM products WHERE sku LIKE ''FAKE-SEED-%'''
  ) AS catalog_products(product_id BIGINT)
)
SELECT
  count(*) FILTER (WHERE fake_products.product_id IS NOT NULL),
  count(*),
  (SELECT count(*) FROM stock_movements)
FROM inventory_stock
LEFT JOIN fake_products USING (product_id);
SQL
)

if (( fake_count < SEED_COUNT )); then
  echo "Inventory solo contiene $fake_count productos fake; se esperaban al menos $SEED_COUNT" >&2
  exit 1
fi

echo "OK database=postgres/$INVENTORY_DATABASE table=inventory_stock fake_rows=$fake_count total_rows=$total_count movements=$movement_count requested=$SEED_COUNT"
