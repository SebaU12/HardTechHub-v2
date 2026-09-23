#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
SCRIPT_DIR="$ROOT_DIR/scripts"
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

docker compose up -d --wait mongodb

docker compose exec -T \
  -e SEED_COUNT="$SEED_COUNT" \
  -e FORCE_SEED="$FORCE_SEED" \
  mongodb mongosh \
  --host localhost \
  --port 27017 \
  --username "${MONGO_APP_USER:-hardtech}" \
  --password "${MONGO_APP_PASSWORD:-hardtech}" \
  --authenticationDatabase hardtech_identity \
  hardtech_identity \
  --quiet \
  --eval 'const loaded = load("/dev/stdin");' < "$SCRIPT_DIR/seed-mongodb-20k.js"
