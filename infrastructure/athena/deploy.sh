#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 || $# -gt 3 ]]; then
  echo "Uso: $0 <bucket-s3> [region] [stack-name]" >&2
  exit 2
fi

DATA_LAKE_BUCKET=$1
AWS_REGION=${2:-${AWS_DEFAULT_REGION:-us-east-1}}
STACK_NAME=${3:-hardtech-athena}
SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)

aws s3api head-bucket --bucket "$DATA_LAKE_BUCKET" --region "$AWS_REGION"
aws s3api put-object --bucket "$DATA_LAKE_BUCKET" --key athena-results/ --region "$AWS_REGION" >/dev/null

aws cloudformation deploy \
  --template-file "$SCRIPT_DIR/template.yaml" \
  --stack-name "$STACK_NAME" \
  --region "$AWS_REGION" \
  --capabilities CAPABILITY_IAM \
  --parameter-overrides DataLakeBucket="$DATA_LAKE_BUCKET" \
  --no-fail-on-empty-changeset

aws cloudformation describe-stacks \
  --stack-name "$STACK_NAME" \
  --region "$AWS_REGION" \
  --query 'Stacks[0].Outputs[*].[OutputKey,OutputValue]' \
  --output table

