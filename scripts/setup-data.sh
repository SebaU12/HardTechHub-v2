#!/bin/bash
# Configura la VM de datos desde cero (PostgreSQL, MySQL, MongoDB).
# Uso: bash scripts/setup-data.sh
# Ejecutar desde la raíz del repositorio: cd ~/app && bash scripts/setup-data.sh

set -e

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
DEPLOY_DIR="$REPO_DIR/deploy"
COMPOSE_FILE="$DEPLOY_DIR/compose.data.yml"
ENV_FILE="$DEPLOY_DIR/.env.data"
cd "$REPO_DIR"

echo "==> [1/3] Creando .env.data en $DEPLOY_DIR..."
cat > "$ENV_FILE" <<'EOF'
POSTGRES_USER=hardtech
POSTGRES_PASSWORD=Hardtech2026!
POSTGRES_READER_USER=hardtech_reader
POSTGRES_READER_PASSWORD=HardtechReader2026!
MYSQL_USER=hardtech
MYSQL_PASSWORD=Hardtech2026!
MYSQL_ROOT_PASSWORD=HardtechRoot2026!
MYSQL_READER_USER=hardtech_reader
MYSQL_READER_PASSWORD=HardtechReader2026!
MONGO_ROOT_PASSWORD=HardtechRoot2026!
MONGO_APP_USER=hardtech
MONGO_APP_PASSWORD=Hardtech2026!
MONGO_READER_USER=hardtech_reader
MONGO_READER_PASSWORD=HardtechReader2026!
EOF
echo "    .env.data creado."

echo "==> [2/3] Iniciando bases de datos..."
docker compose -f "$COMPOSE_FILE" --env-file "$ENV_FILE" up -d

echo "==> [3/3] Esperando 60s para que las BDs inicialicen y ejecuten los scripts de init..."
sleep 60

docker compose -f "$COMPOSE_FILE" --env-file "$ENV_FILE" ps

echo ""
echo "=== Setup de Data VM completado ==="
echo "IP privada de este host (usar como DB_HOST en setup-app.sh):"
hostname -I | awk '{print $1}'
