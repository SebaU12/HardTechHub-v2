#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
cd "$ROOT_DIR"

TEST_PROJECT="hardtech-order-phase3-${$}"
TEST_IMAGE="hardtech-order-phase3:${$}"
export COMPOSE_PROJECT_NAME="$TEST_PROJECT"
export COMPOSE_FILE="$ROOT_DIR/services/order-service/tests/compose.mysql.yml"

cleanup() {
  docker compose down --volumes --remove-orphans >/dev/null 2>&1 || true
}
trap cleanup EXIT

if ! docker network inspect hardtech-net >/dev/null 2>&1; then
  docker network create hardtech-net >/dev/null
fi

cleanup
docker compose up -d mysql

mysql_container="${TEST_PROJECT}-mysql-1"
for _ in $(seq 1 90); do
  health=$(docker inspect --format '{{.State.Health.Status}}' "$mysql_container" 2>/dev/null || true)
  if [[ "$health" == "healthy" ]]; then
    break
  fi
  if [[ "$(docker inspect --format '{{.State.Status}}' "$mysql_container" 2>/dev/null || true)" == "exited" ]]; then
    docker compose logs --no-color mysql >&2
    exit 1
  fi
  sleep 2
done

if [[ "${health:-}" != "healthy" ]]; then
  docker compose logs --no-color mysql >&2
  echo "FALLO MySQL no quedó healthy" >&2
  exit 1
fi

# The image healthcheck can turn green while the entrypoint is still finishing
# the temporary initialization server. Wait until the configured root password
# is usable before applying the migration.
mysql_ready=false
for _ in $(seq 1 60); do
  if docker compose exec -T -e MYSQL_PWD=root mysql \
    mysql --user=root --execute='SELECT 1' >/dev/null 2>&1; then
    mysql_ready=true
    break
  fi
  sleep 2
done
if [[ "$mysql_ready" != "true" ]]; then
  docker compose logs --no-color mysql >&2
  echo "FALLO credenciales MySQL no disponibles" >&2
  exit 1
fi

# Validate the path used for an existing Data VM, twice to prove the migration
# is safe to rerun.
./scripts/setup-orders-inventory-migration.sh
./scripts/setup-orders-inventory-migration.sh

column_count=$(docker compose exec -T mysql mysql \
  --user=root \
  --password=root \
  --batch --skip-column-names \
  --database=hardtech_orders \
  --execute="
    SELECT count(*)
    FROM information_schema.columns
    WHERE table_schema = DATABASE()
      AND table_name = 'orders'
      AND column_name IN (
        'idempotency_key', 'request_hash', 'inventory_reservation_id',
        'inventory_status', 'order_event_key'
      );
  ")

index_count=$(docker compose exec -T mysql mysql \
  --user=root \
  --password=root \
  --batch --skip-column-names \
  --database=hardtech_orders \
  --execute="
    SELECT count(DISTINCT index_name)
    FROM information_schema.statistics
    WHERE table_schema = DATABASE()
      AND table_name = 'orders'
      AND index_name IN (
        'uq_orders_idempotency_key',
        'uq_orders_inventory_reservation_id',
        'idx_orders_inventory_status'
      );
  ")

if [[ "$column_count" != "5" || "$index_count" != "3" ]]; then
  echo "FALLO migración incompleta: columns=$column_count indexes=$index_count" >&2
  exit 1
fi

docker build --tag "$TEST_IMAGE" services/order-service

docker run --rm \
  --network hardtech-net \
  -e ORDER_INTEGRATION_TEST=1 \
  -e MYSQL_HOST="$mysql_container" \
  -e MYSQL_PORT=3306 \
  -e MYSQL_DATABASE=hardtech_orders \
  -e MYSQL_USER=hardtech \
  -e MYSQL_PASSWORD=hardtech \
  "$TEST_IMAGE" \
  python -m unittest discover -s tests -v

echo "OK phase=3 migration_idempotent=true columns=$column_count indexes=$index_count integration=true"
