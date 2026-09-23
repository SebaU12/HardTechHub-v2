#!/bin/bash
# Configura una VM de aplicación desde cero.
# Uso: bash scripts/setup-app.sh <DB_HOST> <API_BASE_URL>
# Ejemplo: bash scripts/setup-app.sh 172.31.27.193 https://abc123.execute-api.us-east-1.amazonaws.com

set -e

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_DIR"

DB_HOST="${1:?ERROR: falta DB_HOST. Uso: $0 <DB_HOST> <API_BASE_URL>}"
API_BASE_URL="${2:?ERROR: falta API_BASE_URL. Uso: $0 <DB_HOST> <API_BASE_URL>}"

echo "==> [1/5] Obteniendo INSTANCE_ID via IMDSv2..."
TOKEN=$(curl -sX PUT "http://169.254.169.254/latest/api/token" \
  -H "X-aws-ec2-metadata-token-ttl-seconds: 21600" 2>/dev/null)
INSTANCE_ID=$(curl -s -H "X-aws-ec2-metadata-token: $TOKEN" \
  http://169.254.169.254/latest/meta-data/instance-id 2>/dev/null || hostname)
echo "    INSTANCE_ID=$INSTANCE_ID"

echo "==> [2/5] Creando .env.app en $REPO_DIR..."
cat > "$REPO_DIR/.env.app" <<EOF
DB_HOST=$DB_HOST
POSTGRES_USER=hardtech
POSTGRES_PASSWORD=Hardtech2026!
MYSQL_USER=hardtech
MYSQL_PASSWORD=Hardtech2026!
MONGO_APP_USER=hardtech
MONGO_APP_PASSWORD=Hardtech2026!
POSTGRES_READER_USER=hardtech_reader
POSTGRES_READER_PASSWORD=HardtechReader2026!
MYSQL_READER_USER=hardtech_reader
MYSQL_READER_PASSWORD=HardtechReader2026!
MONGO_READER_USER=hardtech_reader
MONGO_READER_PASSWORD=HardtechReader2026!
AWS_DEFAULT_REGION=us-east-1
S3_BUCKET=hardtech-datalake
ANALYTICS_BACKEND=athena
ATHENA_DATABASE=hardtech_analytics
ATHENA_WORKGROUP=hardtech-workgroup
API_BASE_URL=$API_BASE_URL
INSTANCE_ID=$INSTANCE_ID
EOF
echo "    .env.app creado."

echo "==> [3/5] Liberando espacio Docker..."
docker system prune -f

echo "==> [4/5] Construyendo imágenes una por una (evita OOM en t3.small)..."
# Los ingestores comparten el mismo contexto (../ingestion), se construye con 'ingestor'
APP_SERVICES=(identity-service catalog-service order-service compatibility-service analytics-service ingestor)

for svc in "${APP_SERVICES[@]}"; do
  echo ""
  echo "--- build: $svc ---"
  docker compose -f deploy/compose.app.yml build --no-cache "$svc"
done

echo "==> [5/5] Iniciando todos los servicios..."
docker compose -f deploy/compose.app.yml up -d --no-deps \
  identity-service catalog-service order-service compatibility-service analytics-service \
  ingestor catalog-ingestor orders-ingestor identity-ingestor

echo ""
echo "Esperando 30s para que arranquen los health checks..."
sleep 30

docker compose -f deploy/compose.app.yml ps

echo ""
echo "=== Setup de App VM completado ==="
echo "DB_HOST:      $DB_HOST"
echo "INSTANCE_ID:  $INSTANCE_ID"
echo "API_BASE_URL: $API_BASE_URL"
