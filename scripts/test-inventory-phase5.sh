#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
cd "$ROOT_DIR"

created_env=false
if [[ ! -f deploy/.env.app ]]; then
  cp deploy/.env.app.example deploy/.env.app
  created_env=true
fi

cleanup() {
  if [[ "$created_env" == true ]]; then
    rm -f deploy/.env.app
  fi
}
trap cleanup EXIT

docker compose -f docker-compose.yml config --quiet
docker compose \
  -f deploy/compose.app.yml \
  --env-file deploy/.env.app.example \
  config --quiet

python3 - <<'PY'
from pathlib import Path
import yaml


class CloudFormationLoader(yaml.SafeLoader):
    pass


def cloudformation_tag(loader, _suffix, node):
    if isinstance(node, yaml.ScalarNode):
        return loader.construct_scalar(node)
    if isinstance(node, yaml.SequenceNode):
        return loader.construct_sequence(node)
    return loader.construct_mapping(node)


CloudFormationLoader.add_multi_constructor("!", cloudformation_tag)

root_compose = yaml.safe_load(Path("docker-compose.yml").read_text())
app_compose = yaml.safe_load(Path("deploy/compose.app.yml").read_text())

for name, compose in (("local", root_compose), ("aws", app_compose)):
    services = compose["services"]
    assert "inventory-service" in services, f"{name}: inventory-service missing"
    assert "inventory-ingestor" in services, f"{name}: inventory-ingestor missing"
    inventory = services["inventory-service"]
    assert "8006:8006" in inventory["ports"], f"{name}: port 8006 missing"
    assert inventory["environment"]["POSTGRES_DB"] in (
        "hardtech_inventory",
        "${INVENTORY_DB:-hardtech_inventory}",
    )
    assert inventory["environment"]["S3_EVENTS_PREFIX"] == "raw/events/inventory/"
    order = services["order-service"]
    assert order["environment"]["INVENTORY_SERVICE_URL"] == "http://inventory-service:8006"
    assert "inventory-service" in order["depends_on"]
    ingestor = services["inventory-ingestor"]
    assert ingestor["command"] == ["python", "inventory_ingestor.py"]
    assert ingestor["environment"]["S3_OUTPUT_PREFIX"] == "processed/snapshots/inventory/"

template = yaml.load(
    Path("deploy/cloudformation.yml").read_text(),
    Loader=CloudFormationLoader,
)
resources = template["Resources"]

assert template["Parameters"]["ManageRootVolumes"]["Default"] == "false"
assert template["Conditions"]["ConfigureRootVolumes"] == [
    "ManageRootVolumes",
    "true",
]
for instance_name in ("AppInstance1", "AppInstance2", "DataInstance"):
    mapping = resources[instance_name]["Properties"]["BlockDeviceMappings"]
    assert mapping[0] == "ConfigureRootVolumes"
    assert mapping[2] == "AWS::NoValue"

ingress = resources["SGApp"]["Properties"]["SecurityGroupIngress"]
api_ingress = next(rule for rule in ingress if rule.get("FromPort") == 8001)
assert api_ingress["ToPort"] == 8005
inventory_ingress = resources["SGAppInventoryIngress"]["Properties"]
assert inventory_ingress["GroupId"] == "SGApp"
assert inventory_ingress["FromPort"] == 8006
assert inventory_ingress["ToPort"] == 8006
assert inventory_ingress["SourceSecurityGroupId"] == "SGALB"

target = resources["TGInventory"]["Properties"]
assert target["Port"] == 8006
assert target["HealthCheckPath"] == "/health"
assert target["TargetType"] == "instance"
assert {(entry["Id"], entry["Port"]) for entry in target["Targets"]} == {
    ("AppInstance1", 8006),
    ("AppInstance2", 8006),
}

inventory_rule = resources["RuleInventory"]["Properties"]
assert inventory_rule["Priority"] == 60
assert inventory_rule["Conditions"][0]["Values"] == ["/api/inventory*"]
assert inventory_rule["Actions"][0]["TargetGroupArn"] == "TGInventory"

docs_rule = resources["RuleInventoryDocs"]["Properties"]
assert docs_rule["Priority"] == 61
assert set(docs_rule["Conditions"][0]["Values"]) == {
    "/inventory/docs*",
    "/inventory/openapi.json",
}

priorities = [
    resource["Properties"]["Priority"]
    for resource in resources.values()
    if resource.get("Type") == "AWS::ElasticLoadBalancingV2::ListenerRule"
]
assert len(priorities) == len(set(priorities)), "ALB listener priorities must be unique"
assert "IamInstanceProfile" not in resources["DataInstance"]["Properties"]
assert template["Outputs"]["InventoryTargetGroupArn"]["Value"] == "TGInventory"

setup_app = Path("scripts/setup-app.sh").read_text()
for service in ("inventory-service", "inventory-ingestor"):
    assert service in setup_app, f"setup-app.sh does not deploy {service}"

print(
    "OK phase=5 local_compose=true aws_compose=true port=8006 "
    "target_group=true alb_rules=true outputs=true"
)
PY

git diff --check
