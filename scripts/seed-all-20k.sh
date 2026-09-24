#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
SEED_COUNT=20000
FORCE_ARGUMENT=()

for argument in "$@"; do
  case "$argument" in
    --force) FORCE_ARGUMENT=(--force) ;;
    *[!0-9]*|'') echo "Uso: $0 [cantidad>=20000] [--force]" >&2; exit 2 ;;
    *) SEED_COUNT=$argument ;;
  esac
done

if (( SEED_COUNT < 20000 )); then
  echo "La cantidad mínima permitida es 20000" >&2
  exit 2
fi

"$ROOT_DIR/scripts/seed-postgres-20k.sh" "$SEED_COUNT" "${FORCE_ARGUMENT[@]}"
"$ROOT_DIR/scripts/seed-inventory-20k.sh" "$SEED_COUNT" "${FORCE_ARGUMENT[@]}"
"$ROOT_DIR/scripts/seed-mysql-20k.sh" "$SEED_COUNT" "${FORCE_ARGUMENT[@]}"
"$ROOT_DIR/scripts/seed-mongodb-20k.sh" "$SEED_COUNT" "${FORCE_ARGUMENT[@]}"
"$ROOT_DIR/scripts/verify-seed-counts.sh" "$SEED_COUNT"

echo "Carga masiva completada para los tres motores y el dominio de inventario."
