#!/usr/bin/env bash
set -euo pipefail

AWS_REGION=${1:-${AWS_DEFAULT_REGION:-us-east-1}}
DATABASE_NAME=${2:-hardtech_analytics}
WORKGROUP_NAME=${3:-hardtech-workgroup}
SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
QUERY_DIR="$SCRIPT_DIR/queries"
QUERY_TIMEOUT_SECONDS=${ATHENA_QUERY_TIMEOUT_SECONDS:-300}

aws athena get-work-group --work-group "$WORKGROUP_NAME" --region "$AWS_REGION" >/dev/null

run_query() {
  local file=$1
  local query_name
  local query_text
  local execution_id
  local state
  local deadline
  query_name=$(basename "$file" .sql)
  query_text=$(<"$file")

  execution_id=$(aws athena start-query-execution \
    --query-string "$query_text" \
    --query-execution-context Database="$DATABASE_NAME" \
    --work-group "$WORKGROUP_NAME" \
    --region "$AWS_REGION" \
    --query 'QueryExecutionId' \
    --output text)

  echo "$query_name: $execution_id"
  deadline=$((SECONDS + QUERY_TIMEOUT_SECONDS))
  while true; do
    state=$(aws athena get-query-execution \
      --query-execution-id "$execution_id" \
      --region "$AWS_REGION" \
      --query 'QueryExecution.Status.State' \
      --output text)
    case "$state" in
      SUCCEEDED)
        break
        ;;
      FAILED|CANCELLED)
        aws athena get-query-execution \
          --query-execution-id "$execution_id" \
          --region "$AWS_REGION" \
          --query 'QueryExecution.Status.[State,StateChangeReason]' \
          --output table >&2
        return 1
        ;;
      *)
        if (( SECONDS >= deadline )); then
          aws athena stop-query-execution --query-execution-id "$execution_id" --region "$AWS_REGION"
          echo "$query_name excedió ${QUERY_TIMEOUT_SECONDS}s y fue cancelada" >&2
          return 1
        fi
        sleep 2
        ;;
    esac
  done

  aws athena get-query-results \
    --query-execution-id "$execution_id" \
    --region "$AWS_REGION" \
    --max-results 20 \
    --query 'ResultSet.Rows[*].Data[*].VarCharValue' \
    --output table
}

found=0
for query_file in "$QUERY_DIR"/*.sql; do
  [[ -e "$query_file" ]] || continue
  found=1
  run_query "$query_file"
done

if [[ $found -eq 0 ]]; then
  echo "No se encontraron consultas en $QUERY_DIR" >&2
  exit 1
fi

echo "Todas las consultas terminaron en SUCCEEDED."
