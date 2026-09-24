#!/usr/bin/env bash
set -euo pipefail

STACK_NAME=${1:-hardtech-stack}
REGION=${2:-us-east-1}

stack_output() {
  aws cloudformation describe-stacks \
    --stack-name "$STACK_NAME" \
    --region "$REGION" \
    --query "Stacks[0].Outputs[?OutputKey=='$1'].OutputValue | [0]" \
    --output text
}

require_output() {
  local value
  value=$(stack_output "$1")
  if [[ -z "$value" || "$value" == "None" ]]; then
    echo "FALLO: el stack no contiene el output $1" >&2
    exit 1
  fi
  printf '%s' "$value"
}

run_ssm() {
  local instance_id=$1
  local label=$2
  local parameters=$3
  local command_id

  command_id=$(aws ssm send-command \
    --instance-ids "$instance_id" \
    --document-name AWS-RunShellScript \
    --comment "HardTech Inventory Phase 5 - $label" \
    --parameters "$parameters" \
    --region "$REGION" \
    --query 'Command.CommandId' \
    --output text)

  aws ssm wait command-executed \
    --command-id "$command_id" \
    --instance-id "$instance_id" \
    --region "$REGION"

  echo "=== $label · $instance_id ==="
  aws ssm get-command-invocation \
    --command-id "$command_id" \
    --instance-id "$instance_id" \
    --region "$REGION" \
    --query 'StandardOutputContent' \
    --output text
}

echo "==> Verificando acceso AWS y outputs del stack..."
aws sts get-caller-identity --region "$REGION" >/dev/null

APP1_ID=$(require_output App1InstanceId)
APP2_ID=$(require_output App2InstanceId)
DATA_ID=$(require_output DataInstanceId)
TG_ARN=$(require_output InventoryTargetGroupArn)
API_URL=$(require_output ApiEndpoint)

echo "==> Verificando dos targets Inventory saludables..."
aws elbv2 describe-target-health \
  --target-group-arn "$TG_ARN" \
  --region "$REGION" \
  --query 'TargetHealthDescriptions[*].[Target.Id,Target.Port,TargetHealth.State,TargetHealth.Reason]' \
  --output table

HEALTHY_COUNT=$(aws elbv2 describe-target-health \
  --target-group-arn "$TG_ARN" \
  --region "$REGION" \
  --query "length(TargetHealthDescriptions[?TargetHealth.State=='healthy'])" \
  --output text)
if [[ "$HEALTHY_COUNT" != "2" ]]; then
  echo "FALLO: se esperaban 2 targets healthy y se encontraron $HEALTHY_COUNT" >&2
  exit 1
fi

echo "==> Verificando Swagger de Inventory a través de API Gateway..."
curl --fail --silent --show-error "$API_URL/inventory/openapi.json" >/dev/null

echo "==> Verificando /health dentro de ambas App VM mediante SSM..."
HEALTH_COMMAND='{"commands":["curl --fail --silent --show-error http://localhost:8006/health"]}'
run_ssm "$APP1_ID" "inventory-health" "$HEALTH_COMMAND"
run_ssm "$APP2_ID" "inventory-health" "$HEALTH_COMMAND"

echo "==> CPU reciente, memoria, disco y consumo Docker de las tres EC2..."
START_TIME=$(date -u --date='20 minutes ago' '+%Y-%m-%dT%H:%M:%SZ')
END_TIME=$(date -u '+%Y-%m-%dT%H:%M:%SZ')
CAPACITY_COMMAND='{"commands":["echo HOST=$(hostname)","uptime","free -h","df -h /","docker stats --no-stream || true"]}'

for INSTANCE_ID in "$APP1_ID" "$APP2_ID" "$DATA_ID"; do
  echo "=== CPU CloudWatch · $INSTANCE_ID ==="
  aws cloudwatch get-metric-statistics \
    --namespace AWS/EC2 \
    --metric-name CPUUtilization \
    --dimensions "Name=InstanceId,Value=$INSTANCE_ID" \
    --statistics Average Maximum \
    --period 300 \
    --start-time "$START_TIME" \
    --end-time "$END_TIME" \
    --region "$REGION" \
    --query 'sort_by(Datapoints,&Timestamp)[-1].[Timestamp,Average,Maximum]' \
    --output table

  echo "=== Volúmenes EBS · $INSTANCE_ID ==="
  aws ec2 describe-volumes \
    --filters "Name=attachment.instance-id,Values=$INSTANCE_ID" \
    --region "$REGION" \
    --query 'Volumes[*].[VolumeId,Size,VolumeType,State]' \
    --output table

  SSM_STATUS=$(aws ssm describe-instance-information \
    --filters "Key=InstanceIds,Values=$INSTANCE_ID" \
    --region "$REGION" \
    --query 'InstanceInformationList[0].PingStatus' \
    --output text 2>/dev/null || true)
  if [[ "$SSM_STATUS" == "Online" ]]; then
    run_ssm "$INSTANCE_ID" "capacity" "$CAPACITY_COMMAND"
  else
    echo "AVISO: $INSTANCE_ID no está administrada por SSM; revise memoria y df -h por SSH."
  fi
done

echo "OK phase=5 targets_healthy=2 api_gateway=true health_checks=true cloudwatch_ebs_reviewed=true"
