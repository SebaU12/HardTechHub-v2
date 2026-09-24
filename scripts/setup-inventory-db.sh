#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
cd "$ROOT_DIR"

POSTGRES_READER_USER=${POSTGRES_READER_USER:-hardtech_reader}
POSTGRES_READER_PASSWORD=${POSTGRES_READER_PASSWORD:-hardtech_reader}
INVENTORY_DB=${INVENTORY_DB:-hardtech_inventory}
INVENTORY_DB_USER=${INVENTORY_DB_USER:-hardtech_inventory}
INVENTORY_DB_PASSWORD=${INVENTORY_DB_PASSWORD:-hardtech_inventory}

docker compose up -d --wait postgres

docker compose exec -T \
  -e POSTGRES_READER_USER="$POSTGRES_READER_USER" \
  -e POSTGRES_READER_PASSWORD="$POSTGRES_READER_PASSWORD" \
  -e INVENTORY_DB="$INVENTORY_DB" \
  -e INVENTORY_DB_USER="$INVENTORY_DB_USER" \
  -e INVENTORY_DB_PASSWORD="$INVENTORY_DB_PASSWORD" \
  postgres bash /docker-entrypoint-initdb.d/03-inventory.sh

echo "OK database=$INVENTORY_DB owner=$INVENTORY_DB_USER reader=$POSTGRES_READER_USER"
