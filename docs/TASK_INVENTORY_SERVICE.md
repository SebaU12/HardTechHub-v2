# Task — Nuevo microservicio de inventario

## Objetivo

Agregar un sexto microservicio llamado **Inventory Service** para controlar el
stock de los productos, reservar unidades durante una compra, confirmar o
liberar reservas y generar información analítica de inventario.

El servicio debe integrarse con Catalog, Orders, el Data Lake, Glue, Athena,
API Gateway, el ALB y el frontend sin modificar la responsabilidad principal
de los microservicios existentes.

## Resultado esperado

Al finalizar, el sistema debe impedir que se creen pedidos con más unidades de
las disponibles y debe permitir demostrar este flujo:

```text
Frontend
   │
   ├── consulta disponibilidad
   │
   └── crea pedido
          ↓
     Order Service
          ↓ reserva
     Inventory Service
          ↓
     PostgreSQL: hardtech_inventory
          ↓ eventos/snapshots
     S3 → Glue → Athena → Analytics
```

## Decisiones de diseño propuestas

Las decisiones definitivas de esta sección se detallan en
[Diseño aprobado de Inventory Service](INVENTORY_DESIGN.md).

- Nombre: `inventory-service`.
- Tecnología recomendada: **Python + FastAPI**, para reutilizar patrones de
  Identity, Orders y Analytics.
- Puerto de aplicación: **8006**.
- Persistencia: base lógica independiente `hardtech_inventory` dentro del
  PostgreSQL existente en la Data VM.
- El servicio será el único propietario de las tablas de inventario.
- `product_id` será una referencia lógica a Catalog; no habrá una FK física
  entre bases de datos.
- Las dos App VM ejecutarán una réplica del servicio.
- La concurrencia se controlará mediante transacciones y bloqueo de filas
  (`SELECT ... FOR UPDATE`) o actualización atómica equivalente.
- Las operaciones de reserva y confirmación deberán ser idempotentes.
- El alcance académico no incluirá pagos, proveedores ni bodegas múltiples.

## Modelo de datos propuesto

### `inventory_stock`

| Campo | Tipo | Regla |
|---|---|---|
| `product_id` | `BIGINT` | PK; referencia lógica a Catalog |
| `available_quantity` | `INTEGER` | No negativo |
| `reserved_quantity` | `INTEGER` | No negativo |
| `minimum_quantity` | `INTEGER` | Umbral para stock bajo |
| `version` | `BIGINT` | Control de concurrencia |
| `created_at` | `TIMESTAMPTZ` | Fecha de creación |
| `updated_at` | `TIMESTAMPTZ` | Última modificación |

La cantidad utilizable será:

```text
sellable_quantity = available_quantity - reserved_quantity
```

### `inventory_reservations`

| Campo | Tipo | Regla |
|---|---|---|
| `id` | `UUID` | PK |
| `idempotency_key` | `VARCHAR(100)` | UNIQUE |
| `user_id` | `VARCHAR(80)` | Referencia lógica al usuario |
| `order_id` | `BIGINT` | UNIQUE, nullable hasta confirmar |
| `status` | `VARCHAR(20)` | `ACTIVE`, `CONFIRMED`, `RELEASED`, `EXPIRED`, `CANCELLED` |
| `expires_at` | `TIMESTAMPTZ` | Vencimiento de la reserva |
| `created_at` | `TIMESTAMPTZ` | Fecha de creación |
| `updated_at` | `TIMESTAMPTZ` | Última modificación |

### `inventory_reservation_items`

| Campo | Tipo | Regla |
|---|---|---|
| `reservation_id` | `UUID` | PK/FK → `inventory_reservations.id` |
| `product_id` | `BIGINT` | PK; referencia lógica a Catalog |
| `quantity` | `INTEGER` | Mayor que cero |

### `stock_movements`

| Campo | Tipo | Regla |
|---|---|---|
| `id` | `BIGSERIAL` | PK |
| `product_id` | `BIGINT` | Referencia lógica a Catalog |
| `movement_type` | `VARCHAR(30)` | Entrada, ajuste, confirmación o liberación |
| `quantity` | `INTEGER` | Variación registrada |
| `reservation_id` | `UUID` | Referencia opcional a la reserva |
| `order_id` | `BIGINT` | Referencia lógica opcional al pedido |
| `reason` | `TEXT` | Motivo del movimiento |
| `created_at` | `TIMESTAMPTZ` | Fecha del movimiento |

El diseño definitivo también agrega `request_hash` a las reservas y
`quantity_before`/`quantity_after` a los movimientos para soportar idempotencia
y auditoría.

## Contrato REST propuesto

| Método | Ruta | Responsabilidad |
|---|---|---|
| `GET` | `/api/inventory/{product_id}` | Consultar disponibilidad |
| `GET` | `/api/inventory/low-stock` | Listar productos bajo el mínimo |
| `POST` | `/api/inventory/adjustments` | Agregar o corregir stock |
| `POST` | `/api/inventory/reservations` | Reservar productos de manera atómica |
| `POST` | `/api/inventory/reservations/{id}/confirm` | Asociar pedido y descontar stock |
| `DELETE` | `/api/inventory/reservations/{id}` | Liberar una reserva activa |
| `POST` | `/api/inventory/reservations/{id}/cancel` | Restaurar stock de una orden cancelada |
| `GET` | `/api/inventory/reservations/{id}` | Consultar estado de una reserva |
| `GET` | `/health` | Health check del ALB |

Ejemplo de reserva:

```http
POST /api/inventory/reservations
Idempotency-Key: 28ce3c45-6280-4dc6-a649-7aa7e2df40ee
```

```json
{
  "user_id": "usr_001",
  "items": [
    {"product_id": 1, "quantity": 1},
    {"product_id": 2, "quantity": 1}
  ]
}
```

Respuesta esperada:

```json
{
  "reservation_id": "e3526442-f196-4a8e-9877-f85372a974a2",
  "status": "ACTIVE",
  "expires_at": "2026-09-23T23:40:00Z"
}
```

Si falta stock, responder `409 Conflict` sin reservar parcialmente ningún
producto.

## Flujo de integración con Orders

1. Orders consulta Catalog para validar productos y precios.
2. Orders reutiliza la clave de idempotencia recibida del frontend y solicita
   la reserva completa.
3. Inventory bloquea las filas involucradas, valida todas las cantidades y
   crea la reserva en una única transacción.
4. Orders crea la orden y los ítems en MySQL.
5. Orders confirma la reserva enviando el `order_id`.
6. Inventory descuenta las unidades y registra movimientos de stock.
7. Si MySQL falla antes de crear la orden, Orders libera la reserva.
8. Una tarea periódica libera reservas `ACTIVE` vencidas.

Para el MVP debe documentarse la ventana de inconsistencia que existiría si la
orden se confirma en MySQL pero falla la llamada final a Inventory. La llamada
de confirmación será idempotente para permitir reintentos seguros.

## Eventos de dominio

Prefijo propuesto:

```text
s3://hardtech-datalake/raw/events/inventory/
```

Eventos mínimos:

- `STOCK_ADJUSTED`
- `STOCK_RESERVED`
- `STOCK_CONFIRMED`
- `STOCK_RELEASED`
- `RESERVATION_EXPIRED`
- `STOCK_RESTORED`
- `LOW_STOCK_DETECTED`

Todos deben utilizar el sobre común del proyecto:

```text
event_id, event_type, timestamp, source, user_id,
session_id, product_id, order_id, payload
```

## Plan por fases

### Fase 0 — Diseño y contratos

- [x] Confirmar el modelo de datos y estados de reserva.
- [x] Definir qué estados de Orders representan falta de stock.
- [x] Definir contratos REST, códigos HTTP y ejemplos OpenAPI.
- [x] Definir timeouts y comportamiento ante fallos de Catalog/Inventory.
- [x] Documentar la estrategia de idempotencia y concurrencia.
- [x] Actualizar los diagramas de arquitectura y entidad–relación.

**Criterio de salida completado:** contrato aprobado y documentado en
[`INVENTORY_DESIGN.md`](INVENTORY_DESIGN.md) antes de escribir migraciones o
lógica.

### Fase 1 — Persistencia

- [ ] Crear `hardtech_inventory` en el PostgreSQL de la Data VM.
- [ ] Crear usuario de escritura exclusivo para Inventory.
- [ ] Crear usuario `hardtech_reader` con acceso de solo lectura.
- [ ] Crear las cuatro tablas, constraints e índices.
- [ ] Preparar script de inicialización idempotente.
- [ ] Crear un seed reproducible para productos de demostración.
- [ ] Probar que recrear la Data VM inicializa la base sin pasos manuales.

**Criterio de salida:** esquema y seed funcionan desde un volumen vacío.

### Fase 2 — Inventory Service

- [ ] Crear `services/inventory-service/`.
- [ ] Implementar conexión PostgreSQL con pool.
- [ ] Implementar consulta de stock y listado de stock bajo.
- [ ] Implementar ajustes de stock.
- [ ] Implementar reserva transaccional de varios productos.
- [ ] Implementar confirmación, liberación y expiración.
- [ ] Agregar health check y documentación OpenAPI.
- [ ] Agregar logs estructurados y manejo uniforme de errores.
- [ ] Agregar pruebas unitarias y de integración.

**Criterio de salida:** todas las rutas funcionan localmente y una solicitud
con stock insuficiente no produce reservas parciales.

### Fase 3 — Integración con Order Service

- [ ] Agregar `INVENTORY_SERVICE_URL` a la configuración de Orders.
- [ ] Reservar inventario antes de insertar el pedido.
- [ ] Confirmar la reserva después de obtener `order_id`.
- [ ] Liberar la reserva cuando falle la transacción de MySQL.
- [ ] Implementar timeout y traducción de errores (`409`, `502`, `503`).
- [ ] Evitar pedidos duplicados mediante una clave de idempotencia.
- [ ] Probar reintentos de confirmación sin doble descuento.

**Criterio de salida:** nunca se crea un pedido exitoso si no existe stock
suficiente, y dos compras simultáneas no pueden vender la misma última unidad.

### Fase 4 — Eventos e ingesta analítica

- [ ] Publicar eventos de inventario en S3 después de cada transición válida.
- [ ] Crear `inventory-ingestor` para snapshots Parquet.
- [ ] Crear prefijo `processed/snapshots/inventory/`.
- [ ] Crear tabla Glue `inventory`.
- [ ] Crear tabla Glue `inventory_events`.
- [ ] Incluir ambas tablas en los crawlers correspondientes.
- [ ] Crear consultas Athena de stock bajo, movimientos y rotación.
- [ ] Incorporar endpoints analíticos en Analytics Service.

**Criterio de salida:** un ajuste y una compra pueden rastrearse desde
PostgreSQL hasta S3, Glue, Athena y la API de Analytics.

### Fase 5 — Docker e infraestructura AWS

- [ ] Agregar Inventory Service e Inventory Ingestor a Compose local.
- [ ] Agregarlos a `deploy/compose.app.yml` para ambas App VM.
- [ ] Publicar `8006:8006` en las App VM.
- [ ] Ampliar `SGApp` de `8001–8005` a `8001–8006`.
- [ ] Crear `hardtech-tg-inventory` en CloudFormation.
- [ ] Registrar App 1 y App 2 en el target group, puerto 8006.
- [ ] Agregar regla ALB `/api/inventory*`, prioridad 60.
- [ ] Agregar reglas de documentación, prioridad 61.
- [ ] Comprobar `/health` en ambas instancias.
- [ ] Revisar CPU, memoria y disco de las tres EC2.

**Criterio de salida:** API Gateway permite acceder a Inventory y los dos
targets aparecen `healthy`.

### Fase 6 — Frontend

- [ ] Mostrar stock disponible en detalle y listado de productos.
- [ ] Desactivar compra cuando no exista disponibilidad.
- [ ] Mostrar un mensaje específico ante `409 Conflict`.
- [ ] Crear una pantalla sencilla de ajustes de inventario.
- [ ] Crear una vista de productos con stock bajo.
- [ ] Consumir al menos dos métodos REST del nuevo servicio.
- [ ] Reconstruir y volver a publicar el ZIP en Amplify.

**Criterio de salida:** se puede consultar y modificar stock desde la web y el
usuario recibe una explicación clara cuando no puede completar una compra.

### Fase 7 — Pruebas de aceptación

- [ ] Consultar stock inicial de un producto.
- [ ] Crear un ajuste positivo y comprobar la nueva cantidad.
- [ ] Crear un pedido y verificar la reducción de stock.
- [ ] Cancelar/liberar una reserva y verificar la devolución de unidades.
- [ ] Intentar comprar más unidades de las disponibles y recibir `409`.
- [ ] Ejecutar dos compras concurrentes sobre la última unidad.
- [ ] Apagar una App VM y confirmar que Inventory sigue respondiendo.
- [ ] Verificar eventos y snapshots en S3.
- [ ] Ejecutar crawlers y consultas Athena.
- [ ] Verificar resultados desde Analytics y desde el frontend.

**Criterio de salida:** todas las evidencias pueden repetirse usando comandos y
datos documentados.

### Fase 8 — Documentación y entrega

- [ ] Actualizar README, arquitectura, ER y guía de despliegue.
- [ ] Documentar variables de entorno sin publicar secretos.
- [ ] Agregar ejemplos `curl` de todos los endpoints.
- [ ] Agregar capturas de targets saludables, S3, Glue, Athena y frontend.
- [ ] Registrar limitaciones del MVP y mejoras futuras.
- [ ] Confirmar que ambos repositorios públicos contienen la versión presentada.

## Consultas analíticas sugeridas

- Productos con stock por debajo del mínimo.
- Unidades disponibles y reservadas por producto.
- Entradas y salidas por rango de fechas.
- Productos con mayor rotación.
- Reservas expiradas por día.
- Pedidos rechazados por falta de stock.

## Riesgos que deben probarse

| Riesgo | Mitigación propuesta |
|---|---|
| Dos usuarios compran la última unidad | Bloqueo de fila y transacción atómica |
| Orders reintenta una solicitud | `idempotency_key` UNIQUE |
| Confirmación repetida | Operación idempotente según estado |
| Orders falla después de reservar | Liberación compensatoria y expiración |
| Inventory cae después del commit de Orders | Reintento de confirmación y estado observable |
| Evento S3 falla después de modificar stock | Registrar error; documentar futura outbox |
| Stock no existe para un producto nuevo | Ajuste/alta explícita validada contra Catalog |
| Las dos App VM ejecutan el expirador | Bloqueo transaccional para evitar doble liberación |

## Fuera del alcance inicial

- Múltiples almacenes o ubicaciones físicas.
- Integración con proveedores.
- Pronóstico automático de demanda.
- Pagos y devoluciones monetarias.
- Mensajería con SQS, SNS, Kafka o EventBridge.
- Seguridad avanzada basada en roles para operaciones administrativas.
- Garantía de eventos mediante patrón transactional outbox.

## Definición de terminado

El task se considera completado cuando:

1. Inventory responde a través de API Gateway y del ALB en el puerto 8006.
2. Las dos App VM aparecen saludables en el target group.
3. Orders reserva y confirma stock antes de responder exitosamente.
4. No existe sobreventa en una prueba concurrente.
5. El frontend consulta y muestra la disponibilidad.
6. Existen al menos dos métodos REST consumidos desde la interfaz.
7. Eventos y snapshots aparecen en S3.
8. Glue y Athena permiten consultar inventario.
9. Analytics expone al menos una métrica de inventario.
10. El despliegue puede repetirse desde cero sin correcciones manuales.
