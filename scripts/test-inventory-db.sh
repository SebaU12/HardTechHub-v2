#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
cd "$ROOT_DIR"

TEST_PROJECT="hardtech-inventory-phase1-${$}"
export COMPOSE_PROJECT_NAME="$TEST_PROJECT"

cleanup() {
  docker compose down --volumes --remove-orphans >/dev/null 2>&1 || true
}
trap cleanup EXIT

cleanup
docker compose up -d --wait postgres

# Re-run the installer against an already initialized volume. This is the path
# used by an existing Data VM and must remain idempotent.
./scripts/setup-inventory-db.sh

./scripts/seed-postgres-20k.sh 20000
./scripts/seed-inventory-20k.sh 20000

read -r first_stock_count first_movement_count < <(
  docker compose exec -T postgres psql \
    --username hardtech \
    --dbname hardtech_inventory \
    --tuples-only --no-align \
    --field-separator=' ' \
    --command "SELECT (SELECT count(*) FROM inventory_stock), (SELECT count(*) FROM stock_movements);"
)

./scripts/seed-inventory-20k.sh 20000

read -r second_stock_count second_movement_count < <(
  docker compose exec -T postgres psql \
    --username hardtech \
    --dbname hardtech_inventory \
    --tuples-only --no-align \
    --field-separator=' ' \
    --command "SELECT (SELECT count(*) FROM inventory_stock), (SELECT count(*) FROM stock_movements);"
)

if [[ "$first_stock_count" != "$second_stock_count" || "$first_movement_count" != "$second_movement_count" ]]; then
  echo "FALLO seed no idempotente: stock $first_stock_count/$second_stock_count movements $first_movement_count/$second_movement_count" >&2
  exit 1
fi

table_count=$(docker compose exec -T postgres psql \
  --username hardtech \
  --dbname hardtech_inventory \
  --tuples-only --no-align \
  --command "
    SELECT count(*)
    FROM information_schema.tables
    WHERE table_schema = 'public'
      AND table_name IN (
        'inventory_stock',
        'inventory_reservations',
        'inventory_reservation_items',
        'stock_movements'
      );
  ")

if (( table_count != 4 )); then
  echo "FALLO esquema incompleto: tables=$table_count" >&2
  exit 1
fi

docker compose exec -T \
  -e PGPASSWORD=hardtech_inventory \
  postgres psql \
    --host localhost \
    --username hardtech_inventory \
    --dbname hardtech_inventory \
    --set ON_ERROR_STOP=1 \
    --command "BEGIN; INSERT INTO inventory_stock (product_id, available_quantity) VALUES (999999999, 10); ROLLBACK;" \
    >/dev/null

docker compose exec -T \
  -e PGPASSWORD=hardtech_reader \
  postgres psql \
    --host localhost \
    --username hardtech_reader \
    --dbname hardtech_inventory \
    --set ON_ERROR_STOP=1 \
    --command "SELECT count(*) FROM inventory_stock;" \
    >/dev/null

set +e
docker compose exec -T \
  -e PGPASSWORD=hardtech_reader \
  postgres psql \
    --host localhost \
    --username hardtech_reader \
    --dbname hardtech_inventory \
    --set ON_ERROR_STOP=1 \
    --command "INSERT INTO inventory_stock (product_id, available_quantity) VALUES (999999998, 10);" \
    >/dev/null 2>&1
reader_write_exit=$?

docker compose exec -T postgres psql \
  --username hardtech \
  --dbname hardtech_inventory \
  --set ON_ERROR_STOP=1 \
  --command "INSERT INTO inventory_stock (product_id, available_quantity) VALUES (999999997, -1);" \
  >/dev/null 2>&1
negative_stock_exit=$?
set -e

if (( reader_write_exit == 0 )); then
  echo "FALLO hardtech_reader pudo escribir en inventario" >&2
  exit 1
fi
if (( negative_stock_exit == 0 )); then
  echo "FALLO el constraint permitió stock negativo" >&2
  exit 1
fi

echo "OK fresh_database=true tables=$table_count stock_rows=$second_stock_count movements=$second_movement_count seed_idempotent=true reader_readonly=true constraints=true"
