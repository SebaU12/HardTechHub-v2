#!/usr/bin/env bash
set -euo pipefail

AWS_REGION=${1:-${AWS_DEFAULT_REGION:-us-east-1}}
DATABASE_NAME=${2:-hardtech_analytics}
CRAWLERS=(hardtech-snapshots-crawler hardtech-events-crawler)

start_when_ready() {
  local crawler=$1
  local state
  state=$(aws glue get-crawler --name "$crawler" --region "$AWS_REGION" --query 'Crawler.State' --output text)
  if [[ "$state" == "READY" ]]; then
    echo "Iniciando $crawler"
    aws glue start-crawler --name "$crawler" --region "$AWS_REGION"
  else
    echo "$crawler ya está en estado $state; se esperará su finalización"
  fi
}

wait_until_ready() {
  local crawler=$1
  local state
  while true; do
    state=$(aws glue get-crawler --name "$crawler" --region "$AWS_REGION" --query 'Crawler.State' --output text)
    if [[ "$state" == "READY" ]]; then
      break
    fi
    echo "$crawler: $state"
    sleep 10
  done

  aws glue get-crawler \
    --name "$crawler" \
    --region "$AWS_REGION" \
    --query 'Crawler.LastCrawl.[Status,ErrorMessage,LogGroup,LogStream]' \
    --output table

  local status
  status=$(aws glue get-crawler --name "$crawler" --region "$AWS_REGION" --query 'Crawler.LastCrawl.Status' --output text)
  if [[ "$status" != "SUCCEEDED" ]]; then
    echo "El crawler $crawler terminó con estado $status" >&2
    return 1
  fi
}

for crawler in "${CRAWLERS[@]}"; do
  start_when_ready "$crawler"
done

for crawler in "${CRAWLERS[@]}"; do
  wait_until_ready "$crawler"
done

"$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/validate-catalog.sh" "$AWS_REGION" "$DATABASE_NAME"

