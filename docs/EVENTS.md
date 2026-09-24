# Contratos de eventos de HardTech Hub

## Propósito

Este documento define el formato de los eventos que los microservicios escriben en el data lake. S3 funciona como destino analítico compartido; no reemplaza las bases operacionales ni implementa mensajería transaccional.

Los eventos permiten relacionar actividad de usuarios, catálogo, compatibilidad y órdenes mediante Glue y Athena sin que un servicio acceda directamente a la base de datos de otro.

## Sobre común

Todo evento utiliza la misma estructura exterior:

```json
{
  "event_id": "evt_a1b2c3d4",
  "event_type": "ORDER_CREATED",
  "timestamp": "2026-09-23T15:00:00Z",
  "source": "order-service",
  "user_id": "usr_001",
  "session_id": null,
  "product_id": null,
  "order_id": 25,
  "payload": {}
}
```

| Campo | Tipo | Requerido | Descripción |
|---|---|---:|---|
| `event_id` | string | Sí | ID único con formato `evt_*` |
| `event_type` | string | Sí | Nombre en mayúsculas y snake case |
| `timestamp` | string | Sí | Fecha UTC en ISO 8601 sin milisegundos |
| `source` | string | Sí | Componente que produjo el evento |
| `user_id` | string o null | No | Usuario relacionado |
| `session_id` | string o null | No | Sesión de navegación |
| `product_id` | integer o null | No | Producto principal relacionado |
| `order_id` | integer o null | No | Orden relacionada |
| `payload` | object | Sí | Datos específicos del evento |

Los campos opcionales aparecen como `null` cuando no aplican. Esto mantiene una estructura predecible para pandas, Parquet, Glue y Athena.

## Convenciones

- Fechas en UTC con formato `YYYY-MM-DDTHH:MM:SSZ`.
- Importes monetarios como strings decimales.
- IDs relacionales como enteros y IDs de usuario como strings.
- Un evento representa un hecho ocurrido; no debe modificarse después de escribirse.
- Las claves nuevas del `payload` deben ser compatibles con lectores anteriores.
- No se escriben contraseñas, hashes, tokens, secretos ni credenciales.
- Identity tampoco escribe correos en el data lake del MVP.

## Organización en S3

```text
raw/events/<dominio>/
  year=YYYY/
    month=MM/
      day=DD/
        <event_type>_<event_id>.json
```

Prefijos por productor:

| Productor | Prefijo |
|---|---|
| Identity Service | `raw/events/identity/` |
| Catalog Service | `raw/events/catalog/` |
| Order Service | `raw/events/orders/` |
| Compatibility Service | `raw/events/compatibility/` |
| Ingestor de navegación | `raw/events/navigation/` |
| Inventory Service | `raw/events/inventory/` |

Analytics utiliza `raw/events/` como prefijo raíz y, por tanto, descubre recursivamente todos los dominios.

Los archivos del ingestor pueden contener una lista de sobres porque se escriben por lotes. Los archivos producidos por una operación de negocio contienen un solo sobre. Analytics admite ambas formas.

## Eventos de navegación

Estos eventos son sintéticos hasta que exista el frontend. Todos usan:

```json
{
  "source": "synthetic-ingestor",
  "user_id": "usr_007",
  "session_id": "sess_a1b2c3",
  "product_id": 1,
  "order_id": null,
  "payload": {
    "category": "CPU"
  }
}
```

### `PRODUCT_VIEW`

Indica que un producto fue visualizado.

- `product_id`: requerido.
- `payload.category`: categoría simulada.

### `PRODUCT_SEARCH`

Indica una búsqueda. En el MVP no se conserva el texto buscado.

- `product_id`: null.
- `payload.category`: categoría simulada.

### `ADD_TO_CART`

Indica que se agregó un producto al carrito simulado.

- `product_id`: requerido.
- `payload.category`: categoría simulada.

### `REMOVE_FROM_CART`

Indica que se retiró un producto del carrito simulado.

- `product_id`: requerido.
- `payload.category`: categoría simulada.

## Eventos de órdenes

### `ORDER_CREATED`

Estado: **implementado**.

Se produce después de confirmar en MySQL la cabecera y todos los ítems.

```json
{
  "event_id": "evt_a1b2c3d4",
  "event_type": "ORDER_CREATED",
  "timestamp": "2026-09-23T15:00:00Z",
  "source": "order-service",
  "user_id": "usr_demo_001",
  "session_id": null,
  "product_id": null,
  "order_id": 25,
  "payload": {
    "status": "PENDING",
    "total_amount": "1794.88",
    "item_count": 1
  }
}
```

Si S3 falla después del commit, la orden permanece creada y la respuesta contiene `event_published: false`. El MVP no implementa outbox ni reintento persistente.

### `ORDER_STATUS_CHANGED`

Estado: **implementado**.

```json
{
  "event_type": "ORDER_STATUS_CHANGED",
  "source": "order-service",
  "user_id": "usr_demo_001",
  "order_id": 25,
  "payload": {
    "previous_status": "PENDING",
    "new_status": "PAID",
    "total_amount": "1794.88"
  }
}
```

Se publica después del commit MySQL. Una falla de S3 no revierte el nuevo
estado; la respuesta informa `event_published: false`.

## Eventos de compatibilidad

### `COMPATIBILITY_CHECKED`

Estado: **implementado**.

```json
{
  "event_type": "COMPATIBILITY_CHECKED",
  "source": "compatibility-service",
  "user_id": "usr_demo_001",
  "session_id": "sess_a1b2c3",
  "payload": {
    "compatible": false,
    "rules": ["CPU_SOCKET", "RAM_TYPE", "PSU_POWER"],
    "failed_rules": ["PSU_POWER"],
    "components": {
      "cpu": 1,
      "motherboard": 2,
      "gpu": 3,
      "psu": 5
    }
  }
}
```

El payload real también conserva `checks` con el estado y detalle de cada
regla. Si S3 falla, el resultado de compatibilidad se devuelve normalmente con
`event_published: false`.

## Eventos de catálogo

Estado: **implementados**.

| Evento | Momento |
|---|---|
| `PRODUCT_CREATED` | Después de insertar un producto |
| `PRODUCT_UPDATED` | Después de actualizar datos generales o specs |
| `PRODUCT_PRICE_CHANGED` | Cuando el precio anterior y nuevo difieren |
| `PRODUCT_DEACTIVATED` | Después del soft delete |

Ejemplo de cambio de precio:

```json
{
  "event_type": "PRODUCT_PRICE_CHANGED",
  "source": "catalog-service",
  "product_id": 3,
  "payload": {
    "sku": "GPU-NV-4070TI",
    "previous_price": "3299.90",
    "new_price": "3099.90"
  }
}
```

`PRODUCT_CREATED` incluye specs; `PRODUCT_UPDATED` incluye los campos
modificados y `PRODUCT_DEACTIVATED` conserva SKU, nombre, categoría, marca y
último precio. Los errores S3 no revierten la escritura PostgreSQL.

## Eventos de identidad

### `USER_REGISTERED`

Estado: **implementado**.

```json
{
  "event_type": "USER_REGISTERED",
  "source": "identity-service",
  "user_id": "usr_001",
  "payload": {
    "roles": ["customer"],
    "currency": "PEN",
    "theme": "dark",
    "registered_at": "2026-09-23T15:00:00+00:00"
  }
}
```

No contiene `email`, `password_hash` ni el JWT. Si S3 falla, el usuario
permanece registrado y la respuesta informa `event_published: false`.

## Eventos de inventario

Estado: **implementados**.

| Evento | Momento |
|---|---|
| `STOCK_ADJUSTED` | Después de crear o modificar stock físico |
| `STOCK_RESERVED` | Después de reservar atómicamente todos los productos |
| `STOCK_CONFIRMED` | Después de confirmar la venta y descontar stock físico |
| `STOCK_RELEASED` | Después de liberar una reserva activa |
| `RESERVATION_EXPIRED` | Después de que el expirador libera una reserva vencida |
| `STOCK_RESTORED` | Después de cancelar una venta confirmada y restaurar unidades |
| `LOW_STOCK_DETECTED` | Cuando el stock vendible cruza el mínimo configurado |

Los eventos de reserva incluyen `reservation_id`, estado, vencimiento e ítems
en `payload`. Los ajustes incluyen cantidades anterior/posterior, delta, stock
vendible, mínimo y motivo. `LOW_STOCK_DETECTED` usa `product_id` en el sobre y
conserva las cantidades que provocaron la detección.

La publicación ocurre después del commit PostgreSQL. Un error S3 no revierte
la operación y se refleja como `event_published: false`. Las repeticiones
idempotentes de reserva, confirmación, liberación o restauración no vuelven a
publicar el hecho ya registrado. El prefijo es `raw/events/inventory/`.

## Variables de entorno

Todos los productores utilizan:

| Variable | Descripción |
|---|---|
| `AWS_ACCESS_KEY_ID` | Solo desarrollo local (`test`); en EC2 se usa un rol IAM |
| `AWS_SECRET_ACCESS_KEY` | Solo desarrollo local (`test`); no se configura en EC2 |
| `AWS_DEFAULT_REGION` | Región AWS |
| `S3_ENDPOINT_URL` | Endpoint LocalStack; se omite o adapta en AWS |
| `S3_BUCKET` | Bucket del data lake |
| `S3_EVENTS_PREFIX` | Prefijo propio del dominio |

El ingestor también utiliza `S3_PROCESSED_PREFIX` para su salida Parquet.
En AWS, `S3_ENDPOINT_URL` se omite para usar S3 administrado. La conexión de
Identity a MongoDB se configura por separado mediante `MONGODB_URI`.

## Compatibilidad de esquema

Antes de cambiar un contrato:

1. actualizar este documento;
2. comprobar que Analytics tolera el cambio;
3. actualizar el modelo Parquet correspondiente;
4. revisar el esquema en Glue;
5. actualizar las consultas Athena afectadas.

Los eventos ya escritos son inmutables y no se reescriben como parte de un cambio normal.
