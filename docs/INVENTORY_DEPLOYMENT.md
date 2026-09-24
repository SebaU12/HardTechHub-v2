# Despliegue de Inventory Service en AWS

Esta guía aplica la Fase 5 sobre el stack existente. CloudFormation agrega el
puerto `8006`, el target group de Inventory y las reglas del ALB, pero una
actualización del stack no vuelve a ejecutar el `UserData` de las EC2 ya
creadas. Por eso las bases y los contenedores deben actualizarse explícitamente.

## 1. Preparar la Data VM

En la VM de datos:

```bash
cd ~/app
git pull

export COMPOSE_FILE="$PWD/deploy/compose.data.yml"
export COMPOSE_PROJECT_NAME=deploy

set -a
source deploy/.env.data
set +a

./scripts/setup-inventory-db.sh
./scripts/setup-orders-inventory-migration.sh
./scripts/seed-inventory-20k.sh 20000
```

Los dos scripts de esquema son idempotentes. No eliminan los productos,
pedidos ni usuarios existentes.

## 2. Actualizar CloudFormation

En la consola web de AWS abra **CloudFormation → Stacks**, seleccione el stack
actual y elija **Update**. Seleccione **Replace current template**, cargue
`deploy/cloudformation.yml`, conserve los valores actuales de los parámetros y
confirme la actualización. Espere a que el estado sea
`UPDATE_COMPLETE` antes de tocar las App VM.

La actualización:

- agrega una regla independiente en `SGApp` para el puerto `8006`, sin
  modificar ni reemplazar las EC2 existentes;
- crea `hardtech-tg-inventory` con ambas App VM en `8006`;
- enruta `/api/inventory*` con prioridad `60`;
- enruta `/inventory/docs*` y `/inventory/openapi.json` con prioridad `61`;
- expone IDs de las tres EC2 y el ARN del target group como outputs.

## 3. Actualizar las dos App VM

Ejecute en App 1 y App 2, usando la IP privada actual de la Data VM y el output
`ApiEndpoint`:

```bash
cd ~/app
git pull
bash scripts/setup-app.sh \
  172.31.29.164 \
  https://s7d3vxbohi.execute-api.us-east-1.amazonaws.com
```

El script construye Inventory una sola vez por VM, levanta
`inventory-service`, configura Orders con
`http://inventory-service:8006` y activa `inventory-ingestor` cada 300 segundos.

Comprobación rápida en cada App VM:

```bash
curl --fail http://localhost:8006/health
docker compose -f deploy/compose.app.yml --env-file deploy/.env.app ps
docker compose -f deploy/compose.app.yml --env-file deploy/.env.app \
  logs --tail=100 inventory-service inventory-ingestor order-service
```

## 4. Validación AWS completa

Desde una terminal con AWS CLI, acceso a SSM y `curl`:

```bash
./scripts/verify-inventory-aws.sh hardtech-stack us-east-1
```

El verificador exige dos targets `healthy`, comprueba OpenAPI a través de API
Gateway, ejecuta `/health` dentro de ambas App VM y muestra CPU, memoria, disco,
volúmenes EBS y consumo de contenedores de las tres EC2.

Si SSM responde `TargetNotConnected`, confirme que la instancia está encendida,
que SSM Agent funciona y que `LabInstanceProfile` permite Systems Manager.

## 5. Prueba funcional mínima

```bash
export API_URL=https://s7d3vxbohi.execute-api.us-east-1.amazonaws.com

curl --fail "$API_URL/api/inventory/1"

curl --fail --show-error \
  -X POST "$API_URL/api/inventory/adjustments" \
  -H 'Content-Type: application/json' \
  -d '{"product_id":1,"quantity_delta":1,"minimum_quantity":5,"reason":"Prueba Fase 5"}'

curl --fail "$API_URL/api/analytics/inventory/summary"
curl --fail "$API_URL/inventory/openapi.json" --output /dev/null
```

Los endpoints analíticos reflejarán el nuevo snapshot después del siguiente
ciclo del ingestor y de ejecutar el crawler de snapshots.
