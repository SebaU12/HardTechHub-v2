#!/usr/bin/env bash
# deploy-analytics.sh — Fase 7: activar el data lake en AWS
#
# Requisitos previos:
#   1. Stack CloudFormation (deploy/cloudformation.yml) desplegado.
#   2. VMs App 1 y App 2 corriendo compose.app.yml con los servicios arriba.
#   3. VM de datos corriendo compose.data.yml y carga masiva completada (seed-all-20k.sh).
#   4. AWS CLI configurado con permisos (o ejecutar desde una EC2 con rol de instancia).
#
# Uso:
#   chmod +x scripts/deploy-analytics.sh
#   BUCKET=hardtech-datalake REGION=us-east-1 ./scripts/deploy-analytics.sh
#
# Variables de entorno opcionales:
#   BUCKET            — nombre del bucket S3 (default: hardtech-datalake)
#   REGION            — región AWS (default: us-east-1)
#   WORKGROUP         — Athena workgroup (default: hardtech-workgroup)
#   SNAPSHOTS_CRAWLER — nombre del crawler de snapshots (default: hardtech-snapshots-crawler)
#   EVENTS_CRAWLER    — nombre del crawler de eventos (default: hardtech-events-crawler)
#   API_URL           — URL base de API Gateway (para probar endpoints al final)

set -euo pipefail

BUCKET="${BUCKET:-hardtech-datalake}"
REGION="${REGION:-us-east-1}"
WORKGROUP="${WORKGROUP:-hardtech-workgroup}"
SNAPSHOTS_CRAWLER="${SNAPSHOTS_CRAWLER:-hardtech-snapshots-crawler}"
EVENTS_CRAWLER="${EVENTS_CRAWLER:-hardtech-events-crawler}"
API_URL="${API_URL:-}"

ROOT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
QUERIES_DIR="$ROOT_DIR/infrastructure/athena/queries"

log() { echo "[$(date '+%H:%M:%S')] $*"; }
ok()  { echo "[$(date '+%H:%M:%S')] OK  $*"; }
fail(){ echo "[$(date '+%H:%M:%S')] ERR $*" >&2; exit 1; }

# ─────────────────────────────────────────────────────────────────
# 0. Pre-flight: verificar AWS CLI y bucket
# ─────────────────────────────────────────────────────────────────
log "Verificando acceso a AWS..."
aws sts get-caller-identity --region "$REGION" > /dev/null || fail "Sin credenciales AWS válidas."
aws s3api head-bucket --bucket "$BUCKET" --region "$REGION" 2>/dev/null \
  || fail "Bucket '$BUCKET' no existe. Asegúrate de que el stack CloudFormation esté desplegado."
ok "Bucket $BUCKET accesible."

# ─────────────────────────────────────────────────────────────────
# 1. Ejecutar extractores localmente para generar Parquet y JSON
#    (ejecutar esto en la VM de App o en local con Docker Compose)
# ─────────────────────────────────────────────────────────────────
log "=== PASO 1: Ejecutar extractores (ingestores) ==="
echo ""
echo "  Ejecuta los siguientes comandos EN la VM de aplicación (o localmente):"
echo ""
echo "    # Snapshots Parquet (catalog, orders, identity):"
echo "    docker compose -f deploy/compose.app.yml run --rm catalog-ingestor"
echo "    docker compose -f deploy/compose.app.yml run --rm orders-ingestor"
echo "    docker compose -f deploy/compose.app.yml run --rm identity-ingestor"
echo ""
echo "  Los Parquet se subirán automáticamente a:"
echo "    s3://${BUCKET}/processed/snapshots/{products,orders,order_items,users}/"
echo ""
echo "  Los eventos JSON se subirán a:"
echo "    s3://${BUCKET}/raw/events/{orders,catalog,identity,compatibility,navigation}/"
echo ""
read -rp "¿Los extractores ya se ejecutaron y los datos están en S3? [s/N]: " CONFIRM
[[ "${CONFIRM,,}" == "s" ]] || { echo "Ejecuta los extractores primero y vuelve a correr este script."; exit 0; }

# ─────────────────────────────────────────────────────────────────
# 2. Verificar que existan objetos en S3
# ─────────────────────────────────────────────────────────────────
log "=== PASO 2: Verificar objetos en S3 ==="
for PREFIX in \
    "processed/snapshots/products/" \
    "processed/snapshots/orders/" \
    "processed/snapshots/order_items/" \
    "processed/snapshots/users/" \
    "raw/events/orders/" \
    "raw/events/catalog/" \
    "raw/events/identity/"; do
    COUNT=$(aws s3 ls "s3://${BUCKET}/${PREFIX}" --recursive --region "$REGION" 2>/dev/null | wc -l || echo 0)
    if [[ "$COUNT" -gt 0 ]]; then
        ok "s3://${BUCKET}/${PREFIX} — ${COUNT} objeto(s)"
    else
        echo "  WARN: s3://${BUCKET}/${PREFIX} está vacío — verifica los extractores."
    fi
done

# ─────────────────────────────────────────────────────────────────
# 3. Ejecutar Glue Crawlers
# ─────────────────────────────────────────────────────────────────
log "=== PASO 3: Iniciar Glue Crawlers ==="

start_crawler() {
    local NAME="$1"
    log "Iniciando crawler: $NAME"
    aws glue start-crawler --name "$NAME" --region "$REGION" 2>/dev/null || {
        STATE=$(aws glue get-crawler --name "$NAME" --region "$REGION" \
            --query 'Crawler.State' --output text)
        log "Crawler $NAME en estado $STATE — esperando..."
    }
    for i in $(seq 1 30); do
        STATE=$(aws glue get-crawler --name "$NAME" --region "$REGION" \
            --query 'Crawler.State' --output text)
        if [[ "$STATE" == "READY" ]]; then
            LAST=$(aws glue get-crawler --name "$NAME" --region "$REGION" \
                --query 'Crawler.LastCrawl.Status' --output text 2>/dev/null || echo "N/A")
            ok "Crawler $NAME finalizado — último estado: $LAST"
            return 0
        fi
        log "  $NAME: $STATE (intento $i/30)..."
        sleep 20
    done
    fail "Timeout esperando crawler $NAME"
}

start_crawler "$SNAPSHOTS_CRAWLER"
start_crawler "$EVENTS_CRAWLER"

# ─────────────────────────────────────────────────────────────────
# 4. Verificar tablas en el catálogo Glue
# ─────────────────────────────────────────────────────────────────
log "=== PASO 4: Verificar tablas Glue ==="
EXPECTED_TABLES="products orders order_items users order_events compatibility_events catalog_events identity_events navigation_events"
for TABLE in $EXPECTED_TABLES; do
    COUNT=$(aws glue get-partitions \
        --database-name hardtech_analytics \
        --table-name "$TABLE" \
        --region "$REGION" \
        --query 'length(Partitions)' \
        --output text 2>/dev/null || echo "0")
    ok "Tabla: $TABLE — ${COUNT} partición(es)"
done

# ─────────────────────────────────────────────────────────────────
# 5. Ejecutar las 9 consultas Athena
# ─────────────────────────────────────────────────────────────────
log "=== PASO 5: Ejecutar consultas Athena ==="
OUTPUT_LOCATION="s3://${BUCKET}/athena-results/"

run_query() {
    local QUERY_FILE="$1"
    local QUERY_NAME
    QUERY_NAME=$(basename "$QUERY_FILE" .sql)
    local SQL
    SQL=$(cat "$QUERY_FILE")

    log "Ejecutando: $QUERY_NAME"
    EXEC_ID=$(aws athena start-query-execution \
        --query-string "$SQL" \
        --work-group "$WORKGROUP" \
        --region "$REGION" \
        --query 'QueryExecutionId' \
        --output text)

    for i in $(seq 1 20); do
        STATUS=$(aws athena get-query-execution \
            --query-execution-id "$EXEC_ID" \
            --region "$REGION" \
            --query 'QueryExecution.Status.State' \
            --output text)
        case "$STATUS" in
            SUCCEEDED)
                ok "$QUERY_NAME — SUCCEEDED (ID: $EXEC_ID)"
                echo "  Resultados: ${OUTPUT_LOCATION}${EXEC_ID}.csv"
                return 0
                ;;
            FAILED|CANCELLED)
                REASON=$(aws athena get-query-execution \
                    --query-execution-id "$EXEC_ID" \
                    --region "$REGION" \
                    --query 'QueryExecution.Status.StateChangeReason' \
                    --output text)
                echo "  WARN $QUERY_NAME — $STATUS: $REASON"
                return 1
                ;;
        esac
        sleep 5
    done
    fail "Timeout en query $QUERY_NAME (ID: $EXEC_ID)"
}

SUCCEEDED=0
FAILED=0
for QUERY_FILE in $(ls "$QUERIES_DIR"/*.sql | sort); do
    if run_query "$QUERY_FILE"; then
        SUCCEEDED=$((SUCCEEDED+1))
    else
        FAILED=$((FAILED+1))
    fi
done

echo ""
log "Resultado consultas Athena: ${SUCCEEDED} SUCCEEDED, ${FAILED} FAILED"
[[ "$FAILED" -eq 0 ]] && ok "Todas las consultas Athena finalizaron correctamente."

# ─────────────────────────────────────────────────────────────────
# 6. Probar endpoints de Analytics via API Gateway
# ─────────────────────────────────────────────────────────────────
log "=== PASO 6: Probar endpoints de Analytics ==="
if [[ -z "$API_URL" ]]; then
    echo ""
    echo "  Variable API_URL no definida. Exporta el endpoint de API Gateway:"
    echo "    export API_URL=https://<api-id>.execute-api.${REGION}.amazonaws.com"
    echo "    BUCKET=$BUCKET REGION=$REGION API_URL=\$API_URL ./scripts/deploy-analytics.sh"
    echo ""
    echo "  O prueba manualmente con curl:"
    echo "    curl -s \$API_URL/api/analytics/event-count    | jq ."
    echo "    curl -s \$API_URL/api/analytics/top-products   | jq ."
    echo "    curl -s \$API_URL/api/analytics/sales-summary  | jq ."
else
    ANALYTICS_ENDPOINTS=(
        "/api/analytics/event-count"
        "/api/analytics/top-products"
        "/api/analytics/sales-summary"
        "/api/analytics/sales-by-category"
        "/api/analytics/high-views-low-sales"
        "/api/analytics/failed-compatibility-rules"
        "/api/analytics/compatible-build-rate"
        "/api/analytics/user-registrations"
        "/api/analytics/funnel"
    )
    for EP in "${ANALYTICS_ENDPOINTS[@]}"; do
        HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" "${API_URL}${EP}" || echo "000")
        BACKEND=$(curl -s "${API_URL}${EP}" 2>/dev/null | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('backend','?'))" 2>/dev/null || echo "?")
        if [[ "$HTTP_CODE" == "200" ]]; then
            ok "${EP} — HTTP ${HTTP_CODE} backend=${BACKEND}"
        else
            echo "  WARN ${EP} — HTTP ${HTTP_CODE}"
        fi
    done
fi

# ─────────────────────────────────────────────────────────────────
# Resumen final
# ─────────────────────────────────────────────────────────────────
echo ""
echo "════════════════════════════════════════════════════════════"
echo "  FASE 7 COMPLETADA"
echo "════════════════════════════════════════════════════════════"
echo "  Bucket:    s3://${BUCKET}/"
echo "  Workgroup: ${WORKGROUP}"
echo "  Consultas: ${SUCCEEDED} SUCCEEDED / ${FAILED} FAILED"
[[ -n "$API_URL" ]] && echo "  API URL:   ${API_URL}"
echo ""
echo "  Próximo paso: Fase 8 — pruebas, seguridad y failover."
echo "════════════════════════════════════════════════════════════"
