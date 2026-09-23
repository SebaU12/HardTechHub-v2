#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
cd "$ROOT_DIR"

docker network inspect hardtech-net >/dev/null 2>&1 || docker network create hardtech-net >/dev/null

docker compose build \
  identity-service \
  catalog-service \
  order-service \
  compatibility-service \
  analytics-service \
  ingestor

echo "Fase 7: todas las pruebas incluidas en las imágenes finalizaron correctamente."
