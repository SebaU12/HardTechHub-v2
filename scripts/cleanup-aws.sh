#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 || $# -gt 2 ]]; then
  echo "Uso: $0 <bucket-s3> [region]" >&2
  exit 2
fi

DATA_LAKE_BUCKET=$1
AWS_REGION=${2:-${AWS_DEFAULT_REGION:-us-east-1}}

aws sts get-caller-identity --region "$AWS_REGION"

delete_stack_if_present() {
  local stack_name=$1
  if aws cloudformation describe-stacks \
    --stack-name "$stack_name" \
    --region "$AWS_REGION" >/dev/null 2>&1; then
    echo "Eliminando stack $stack_name"
    aws cloudformation delete-stack \
      --stack-name "$stack_name" \
      --region "$AWS_REGION"
    aws cloudformation wait stack-delete-complete \
      --stack-name "$stack_name" \
      --region "$AWS_REGION"
  else
    echo "Stack $stack_name no existe; se omite"
  fi
}

# Athena se elimina primero porque su política referencia Glue y el bucket.
delete_stack_if_present hardtech-athena
delete_stack_if_present hardtech-glue-catalog

echo
echo "Stacks eliminados. El bucket se conserva intencionalmente: s3://$DATA_LAKE_BUCKET"
echo "Objetos todavía almacenados:"
aws s3 ls "s3://$DATA_LAKE_BUCKET/" --recursive --summarize || true
