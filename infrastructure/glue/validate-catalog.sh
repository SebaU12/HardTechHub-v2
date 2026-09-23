#!/usr/bin/env bash
set -euo pipefail

AWS_REGION=${1:-${AWS_DEFAULT_REGION:-us-east-1}}
DATABASE_NAME=${2:-hardtech_analytics}
EXPECTED_TABLES=(
  products orders order_items users
  order_events compatibility_events catalog_events identity_events navigation_events
)

aws glue get-database \
  --name "$DATABASE_NAME" \
  --region "$AWS_REGION" \
  --query 'Database.[Name,Description]' \
  --output table

missing=0
for table in "${EXPECTED_TABLES[@]}"; do
  if ! aws glue get-table --database-name "$DATABASE_NAME" --name "$table" --region "$AWS_REGION" >/dev/null 2>&1; then
    echo "FALTA tabla: $table" >&2
    missing=1
    continue
  fi

  partition_keys=$(aws glue get-table \
    --database-name "$DATABASE_NAME" \
    --name "$table" \
    --region "$AWS_REGION" \
    --query 'Table.PartitionKeys[].Name' \
    --output text)
  if [[ "$partition_keys" != $'year\tmonth\tday' ]]; then
    echo "Particiones inesperadas en $table: $partition_keys" >&2
    missing=1
  fi

  partition_count=$(aws glue get-partitions \
    --database-name "$DATABASE_NAME" \
    --table-name "$table" \
    --region "$AWS_REGION" \
    --query 'length(Partitions)' \
    --output text)
  location=$(aws glue get-table \
    --database-name "$DATABASE_NAME" \
    --name "$table" \
    --region "$AWS_REGION" \
    --query 'Table.StorageDescriptor.Location' \
    --output text)
  echo "OK table=$table partitions=$partition_count location=$location"
done

if [[ $missing -ne 0 ]]; then
  exit 1
fi

aws glue get-tables \
  --database-name "$DATABASE_NAME" \
  --region "$AWS_REGION" \
  --query 'TableList[*].[Name,Parameters.classification,StorageDescriptor.Columns[0].Name,StorageDescriptor.Columns[0].Type]' \
  --output table

