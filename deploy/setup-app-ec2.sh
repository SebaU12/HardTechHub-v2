#!/usr/bin/env bash
# setup-app-ec2.sh — instalación y arranque idempotente de la VM de aplicación.
# Ejecutar desde la raíz del repositorio: bash deploy/setup-app-ec2.sh
set -euo pipefail

DEPLOY_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$DEPLOY_DIR")"
COMPOSE_FILE="$DEPLOY_DIR/compose.app.yml"
ENV_FILE="$DEPLOY_DIR/.env.app"

# ── 1. Verificar .env.app ─────────────────────────────────────────────────
if [[ ! -f "$ENV_FILE" ]]; then
  echo "ERROR: No se encontró $ENV_FILE"
  echo "Copiar deploy/.env.app.example a deploy/.env.app y completar los valores."
  exit 1
fi

# ── 2. Verificar Docker (incluido en el AMI) ──────────────────────────────
echo "Docker: $(docker --version)"
echo "Docker Compose: $(docker compose version)"

if ! systemctl is-active --quiet docker; then
  systemctl start docker
fi

# ── 4. Obtener INSTANCE_ID desde metadatos EC2 ────────────────────────────
INSTANCE_ID="${INSTANCE_ID:-}"
if [[ -z "$INSTANCE_ID" ]]; then
  echo "Obteniendo INSTANCE_ID desde metadatos EC2..."
  # Intentar IMDSv2 primero
  TOKEN=$(curl -sf -X PUT "http://169.254.169.254/latest/api/token" \
    -H "X-aws-ec2-metadata-token-ttl-seconds: 21600" 2>/dev/null || true)
  if [[ -n "$TOKEN" ]]; then
    INSTANCE_ID=$(curl -sf -H "X-aws-ec2-metadata-token: $TOKEN" \
      "http://169.254.169.254/latest/meta-data/instance-id" 2>/dev/null || true)
  fi
  # Fallback a IMDSv1 o hostname
  if [[ -z "$INSTANCE_ID" ]]; then
    INSTANCE_ID=$(curl -sf "http://169.254.169.254/latest/meta-data/instance-id" 2>/dev/null \
      || hostname)
  fi
  echo "INSTANCE_ID=$INSTANCE_ID"
fi

# Escribir/actualizar INSTANCE_ID en .env.app
if grep -q "^INSTANCE_ID=" "$ENV_FILE"; then
  sed -i "s/^INSTANCE_ID=.*/INSTANCE_ID=$INSTANCE_ID/" "$ENV_FILE"
else
  echo "INSTANCE_ID=$INSTANCE_ID" >> "$ENV_FILE"
fi

# ── 5. Exportar INSTANCE_ID para docker compose ───────────────────────────
export INSTANCE_ID

# ── 6. Crear red Docker si no existe ─────────────────────────────────────
# compose.app.yml usa la red interna hardtech-app-net (bridge).
# No se requiere red externa.

# ── 7. Construir imágenes ─────────────────────────────────────────────────
echo "Construyendo imágenes..."
docker compose -f "$COMPOSE_FILE" --env-file "$ENV_FILE" build

# ── 8. Arrancar servicios ─────────────────────────────────────────────────
echo "Iniciando servicios..."
docker compose -f "$COMPOSE_FILE" --env-file "$ENV_FILE" up -d

# ── 9. Verificar estado ───────────────────────────────────────────────────
echo ""
echo "Estado de los contenedores:"
docker compose -f "$COMPOSE_FILE" --env-file "$ENV_FILE" ps

echo ""
echo "Setup completado. INSTANCE_ID=$INSTANCE_ID"
echo "Para ver los logs: docker compose -f deploy/compose.app.yml logs -f"
