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

docker compose up -d --wait postgres

docker compose exec -T postgres psql \
  --username hardtech \
  --dbname hardtech_catalog \
  --set ON_ERROR_STOP=1 \
  --set seed_count="$SEED_COUNT" \
  --set force_seed="$FORCE_SEED" <<'SQL'
BEGIN;

DELETE FROM products
WHERE :'force_seed' = 'true'
  AND sku LIKE 'FAKE-SEED-%';

WITH dimensions AS (
    SELECT
        ARRAY(SELECT id FROM categories ORDER BY id) AS category_ids,
        ARRAY(SELECT id FROM brands ORDER BY id) AS brand_ids
),
fake_products AS (
    SELECT
        number,
        category_ids[1 + ((number - 1) % cardinality(category_ids))::integer] AS category_id,
        brand_ids[1 + ((number - 1) % cardinality(brand_ids))::integer] AS brand_id
    FROM generate_series(1, :seed_count::integer) AS series(number)
    CROSS JOIN dimensions
)
INSERT INTO products (
    category_id, brand_id, sku, name, description, price, specs, image_url, is_active
)
SELECT
    category_id,
    brand_id,
    'FAKE-SEED-' || lpad(number::text, 6, '0'),
    'Componente ficticio ' || lpad(number::text, 6, '0'),
    'Dato determinista para pruebas masivas de HardTech Hub',
    round((100 + (number % 500000)::numeric / 100), 2),
    jsonb_build_object(
        'seed', 'rubrica-20k',
        'sequence', number,
        'tier', CASE number % 3 WHEN 0 THEN 'entry' WHEN 1 THEN 'mid' ELSE 'high' END
    ),
    'https://example.com/images/fake-' || lpad(number::text, 6, '0') || '.jpg',
    true
FROM fake_products
ON CONFLICT (sku) DO NOTHING;

COMMIT;
SQL

seeded_count=$(docker compose exec -T postgres psql \
  --username hardtech \
  --dbname hardtech_catalog \
  --tuples-only --no-align \
  --command "SELECT count(*) FROM products WHERE sku LIKE 'FAKE-SEED-%';")

if (( seeded_count < SEED_COUNT )); then
  echo "PostgreSQL solo contiene $seeded_count productos fake; se esperaban al menos $SEED_COUNT" >&2
  exit 1
fi

echo "OK database=postgres table=products fake_rows=$seeded_count requested=$SEED_COUNT"
