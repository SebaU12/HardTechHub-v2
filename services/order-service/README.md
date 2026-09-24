# Order Service

Order Service registra pedidos en MySQL y coordina el descuento de stock con
Inventory Service. La integración usa una reserva compensable para evitar
pedidos sin inventario y reintentos que descuenten unidades más de una vez.

## Crear un pedido

```http
POST /api/orders
Idempotency-Key: checkout-20260923-000001
Content-Type: application/json

{
  "user_id": "usr_demo_001",
  "items": [{"product_id": 1, "quantity": 1}]
}
```

La clave es obligatoria, debe tener entre 16 y 100 caracteres y debe conservarse
al reintentar la misma compra. La primera ejecución devuelve `201`; una
repetición ya completada devuelve `200` con el mismo `order_id`. Reutilizar la
clave con otro cuerpo devuelve `409 IDEMPOTENCY_KEY_REUSED`.

El flujo es:

1. validar los productos en Catalog;
2. reservar todas las unidades en Inventory;
3. guardar el pedido y sus líneas en una transacción MySQL;
4. confirmar la reserva con el `order_id`;
5. publicar `ORDER_CREATED` una sola vez.

Si MySQL falla, se libera la reserva. Si no puede conocerse el resultado de la
confirmación, el pedido queda con `inventory_status=CONFIRMATION_PENDING` y se
responde `503`; repetir la petición con la misma clave reconcilia el estado sin
crear otro pedido. Cancelar una orden confirmada solicita a Inventory restaurar
sus unidades antes de confirmar el cambio comercial.

## Configuración

| Variable | Default | Uso |
|---|---:|---|
| `INVENTORY_SERVICE_URL` | `http://inventory-service:8006` | Base URL de Inventory |
| `INVENTORY_TIMEOUT_SECONDS` | `3` | Timeout por llamada |
| `MYSQL_CONNECT_TIMEOUT_SECONDS` | `3` | Timeout de conexión MySQL |
| `MYSQL_READ_TIMEOUT_SECONDS` | `5` | Timeout de lectura MySQL |
| `MYSQL_WRITE_TIMEOUT_SECONDS` | `5` | Timeout de escritura MySQL |

El cliente reintenta dos veces los errores de red y `5xx`. Los errores de
negocio `4xx` no se reintentan.

## Migración de una Data VM existente

```bash
./scripts/setup-orders-inventory-migration.sh
```

La migración es idempotente. Agrega a `orders` las columnas e índices de
idempotencia, reserva y estado técnico sin eliminar los pedidos existentes. En
la Data VM detecta automáticamente `deploy/.env.data` y el proyecto `deploy`;
en local respeta `COMPOSE_FILE` y `COMPOSE_PROJECT_NAME` si están definidos.

## Pruebas

```bash
./scripts/test-order-inventory-integration.sh
```

La prueba levanta un MySQL temporal, ejecuta dos veces la migración, construye
la imagen y valida stock insuficiente, reintentos, compensación, cancelación y
concurrencia sobre la última unidad.
