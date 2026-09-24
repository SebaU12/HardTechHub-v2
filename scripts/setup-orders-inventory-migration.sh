#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
cd "$ROOT_DIR"

MYSQL_DATABASE=${MYSQL_DATABASE:-hardtech_orders}
COMPOSE=(docker compose)

# On the Data VM, setup-data.sh creates deploy/.env.data and uses the deploy
# Compose project. Local/test callers may keep using COMPOSE_FILE explicitly.
if [[ -z "${COMPOSE_FILE:-}" && -f "$ROOT_DIR/deploy/.env.data" ]]; then
  COMPOSE+=(
    -f "$ROOT_DIR/deploy/compose.data.yml"
    --env-file "$ROOT_DIR/deploy/.env.data"
    -p "${COMPOSE_PROJECT_NAME:-deploy}"
  )
fi

"${COMPOSE[@]}" up -d --wait mysql

"${COMPOSE[@]}" exec -T mysql sh -c \
  'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" exec mysql --user=root --database="$1" --show-warnings' \
    sh "$MYSQL_DATABASE" \
    < infrastructure/mysql/init/02_inventory_integration.sql

echo "OK database=$MYSQL_DATABASE migration=orders_inventory"
