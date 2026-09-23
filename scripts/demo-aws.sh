#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 2 || $# -gt 3 ]]; then
  echo "Uso: $0 <bucket-s3> <analytics-url> [region]" >&2
  exit 2
fi

DATA_LAKE_BUCKET=$1
ANALYTICS_URL=${2%/}
AWS_REGION=${3:-${AWS_DEFAULT_REGION:-us-east-1}}
ROOT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)

aws sts get-caller-identity --region "$AWS_REGION"

"$ROOT_DIR/infrastructure/glue/deploy.sh" "$DATA_LAKE_BUCKET" "$AWS_REGION"
"$ROOT_DIR/infrastructure/glue/run-crawlers.sh" "$AWS_REGION" hardtech_analytics
"$ROOT_DIR/infrastructure/athena/deploy.sh" "$DATA_LAKE_BUCKET" "$AWS_REGION"
"$ROOT_DIR/infrastructure/athena/run-queries.sh" "$AWS_REGION" hardtech_analytics hardtech-workgroup

endpoints=(
  events/count
  top-products
  sales/summary
  sales/by-category
  products/conversion
  compatibility/failure-rules
  compatibility/summary
  users/registrations
  funnel
)

for endpoint in "${endpoints[@]}"; do
  echo
  echo "== ${endpoint} =="
  curl --fail --silent --show-error "$ANALYTICS_URL/api/analytics/$endpoint" | jq .
done

echo
echo "Demostración AWS completada. Tome capturas de Glue, Athena y las respuestas mostradas."
