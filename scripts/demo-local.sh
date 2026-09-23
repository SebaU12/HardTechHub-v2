#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
cd "$ROOT_DIR"

cleanup() {
  if [[ ${KEEP_RUNNING:-0} != "1" ]]; then
    docker compose down >/dev/null
  fi
}
trap cleanup EXIT

wait_for_url() {
  local url=$1
  for _ in {1..60}; do
    if curl --fail --silent "$url" >/dev/null; then
      return 0
    fi
    sleep 2
  done
  echo "Timeout esperando $url" >&2
  return 1
}

show_json() {
  local title=$1
  local payload=$2
  echo
  echo "== $title =="
  jq . <<<"$payload"
}

docker network inspect hardtech-net >/dev/null 2>&1 || docker network create hardtech-net >/dev/null
docker compose up -d --build \
  identity-service catalog-service order-service compatibility-service analytics-service

for port in 8001 8002 8003 8004 8005; do
  wait_for_url "http://localhost:${port}/health"
done

run_id="$(date -u +%Y%m%d%H%M%S)_$$"
email="demo_${run_id}@hardtech.com"

registered=$(curl --fail --silent --show-error \
  -X POST http://localhost:8001/api/auth/register \
  -H 'Content-Type: application/json' \
  -d "{\"email\":\"${email}\",\"password\":\"DemoPass123!\"}")
show_json "1. Usuario registrado" "$registered"
user_id=$(jq -r '.user_id' <<<"$registered")
[[ $(jq -r '.event_published' <<<"$registered") == "true" ]]

product=$(curl --fail --silent --show-error http://localhost:8002/api/products/1)
show_json "2a. Producto consultado" "$product"
product_update=$(jq '{name,description,price:(.price|tonumber),specs,image_url,is_active}' <<<"$product")
updated=$(curl --fail --silent --show-error \
  -X PUT http://localhost:8002/api/products/1 \
  -H 'Content-Type: application/json' \
  -d "$product_update")
show_json "2b. Producto actualizado" "$updated"
[[ $(jq -r '.event_published' <<<"$updated") == "true" ]]

compatible=$(curl --fail --silent --show-error \
  -X POST http://localhost:8004/api/compatibility/check \
  -H 'Content-Type: application/json' \
  -d "{\"user_id\":\"${user_id}\",\"session_id\":\"sess_${run_id}\",\"components\":[{\"type\":\"cpu\",\"product_id\":1},{\"type\":\"motherboard\",\"product_id\":2},{\"type\":\"ram\",\"product_id\":4},{\"type\":\"gpu\",\"product_id\":3},{\"type\":\"psu\",\"product_id\":5}]}")
show_json "3. Build compatible" "$compatible"
[[ $(jq -r '.compatible' <<<"$compatible") == "true" ]]

incompatible=$(curl --fail --silent --show-error \
  -X POST http://localhost:8004/api/compatibility/check \
  -H 'Content-Type: application/json' \
  -d "{\"user_id\":\"${user_id}\",\"components\":[{\"type\":\"cpu\",\"product_id\":3},{\"type\":\"motherboard\",\"product_id\":2}]}")
show_json "4. Build incompatible" "$incompatible"
[[ $(jq -r '.compatible' <<<"$incompatible") == "false" ]]

created_order=$(curl --fail --silent --show-error \
  -X POST http://localhost:8003/api/orders \
  -H 'Content-Type: application/json' \
  -d "{\"user_id\":\"${user_id}\",\"items\":[{\"product_id\":1,\"quantity\":1}]}")
show_json "5. Orden creada" "$created_order"
order_id=$(jq -r '.order_id' <<<"$created_order")
[[ $(jq -r '.event_published' <<<"$created_order") == "true" ]]

paid_order=$(curl --fail --silent --show-error \
  -X PATCH "http://localhost:8003/api/orders/${order_id}/status" \
  -H 'Content-Type: application/json' \
  -d '{"status":"PAID"}')
show_json "6. Orden pagada" "$paid_order"
[[ $(jq -r '.status' <<<"$paid_order") == "PAID" ]]

docker compose build catalog-ingestor orders-ingestor identity-ingestor
docker compose run --rm -e RUN_ONCE=true catalog-ingestor
docker compose run --rm -e RUN_ONCE=true orders-ingestor
docker compose run --rm -e RUN_ONCE=true identity-ingestor
docker compose run --rm --no-deps identity-ingestor python validate_data_lake.py

echo
echo "== 7. Objetos y particiones S3 =="
docker compose exec localstack awslocal s3 ls s3://hardtech-datalake/ --recursive

analytics=$(curl --fail --silent --show-error http://localhost:8005/api/analytics/events/count)
show_json "10 local. Analytics sobre S3" "$analytics"

echo
echo "== Logs recientes de ingesta =="
docker compose logs --no-color --tail=20 catalog-ingestor orders-ingestor identity-ingestor

echo
echo "Demostración local completada. Los pasos 8-10 sobre Glue/Athena se ejecutan con scripts/demo-aws.sh."
