# Base de datos de Inventory Service

La fase 1 agrega la base lógica PostgreSQL `hardtech_inventory` al contenedor
PostgreSQL existente. No crea otro motor ni otro puerto en la Data VM.

## Objetos creados

- Rol propietario `hardtech_inventory`.
- Acceso de lectura para `hardtech_reader`.
- Base `hardtech_inventory`.
- Tablas `inventory_stock`, `inventory_reservations`,
  `inventory_reservation_items` y `stock_movements`.
- Constraints, claves foráneas, índices y triggers de `updated_at`.
- Extensiones `pgcrypto` y `dblink`; `dblink` se utiliza solo para el seed que
  copia los identificadores lógicos del catálogo.

## Inicialización desde cero

Los scripts de `/docker-entrypoint-initdb.d` se ejecutan automáticamente cuando
el volumen de PostgreSQL está vacío:

```bash
docker compose up -d --wait postgres
```

En la Data VM, `scripts/setup-data.sh` genera las variables necesarias antes de
levantar `deploy/compose.data.yml`.

## Agregar Inventory a una Data VM existente

Los scripts de init de PostgreSQL no vuelven a ejecutarse sobre un volumen ya
inicializado. Para agregar la base sin eliminar datos existentes:

```bash
cd ~/app
set -a
source deploy/.env.data
set +a

export COMPOSE_FILE="$PWD/deploy/compose.data.yml"
export COMPOSE_PROJECT_NAME=deploy

./scripts/setup-inventory-db.sh
```

El script es idempotente y puede ejecutarse nuevamente.

## Seed

Primero deben existir los productos de catálogo:

```bash
./scripts/seed-postgres-20k.sh 20000
./scripts/seed-inventory-20k.sh 20000
```

También está integrado en:

```bash
./scripts/seed-all-20k.sh 20000
```

La cantidad inicial es determinista según `product_id`. Una segunda ejecución
no cambia el stock ni duplica movimientos. `--force` restablece las cantidades
de las filas del seed y debe reservarse para datos de demostración.

## Prueba aislada desde volumen vacío

```bash
./scripts/test-inventory-db.sh
```

La prueba utiliza un proyecto Compose temporal y elimina únicamente sus
contenedores y volúmenes al terminar. Comprueba:

- creación de las cuatro tablas;
- carga de al menos 20,000 productos;
- idempotencia del seed;
- escritura con el usuario propietario;
- lectura y rechazo de escritura para `hardtech_reader`;
- rechazo de cantidades negativas.
