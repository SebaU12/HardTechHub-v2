# Carga masiva de datos ficticios

La carga de la rúbrica es una operación manual y única. No forma parte del
arranque de Docker Compose ni de los scripts de inicialización de los motores.
Por defecto crea 20,000 registros deterministas en cada dominio:

- PostgreSQL: 20,000 filas en `products`, relacionadas con `categories` y
  `brands` existentes;
- PostgreSQL Inventory: stock inicial para los 20,000 productos ficticios y
  los productos de demostración;
- MySQL: 20,000 filas en `orders` y una fila relacionada en `order_items` por
  pedido;
- MongoDB: 20,000 documentos en la colección `users` mediante `bulkWrite`.

## Ejecución

Desde la raíz del repositorio:

```bash
./scripts/seed-all-20k.sh
```

La cantidad puede aumentarse, pero nunca ser menor que 20,000:

```bash
./scripts/seed-all-20k.sh 30000
```

También se puede cargar y verificar cada motor por separado:

```bash
./scripts/seed-postgres-20k.sh 20000
./scripts/seed-inventory-20k.sh 20000
./scripts/seed-mysql-20k.sh 20000
./scripts/seed-mongodb-20k.sh 20000
./scripts/verify-seed-counts.sh 20000
```

Los scripts levantan únicamente los contenedores de datos que necesitan y
conservan los volúmenes al terminar.

## Idempotencia y recarga

Los datos usan identificadores reservados y reproducibles:

- SKU `FAKE-SEED-000001` en PostgreSQL;
- `product_id` del catálogo y cantidades deterministas en Inventory;
- usuario `fake_seed_000001` en MySQL;
- `user_id` y correo derivados de `fake_seed_000001` en MongoDB;
- marcador `seed_version: rubrica-20k-v1` en los documentos MongoDB.

Una segunda ejecución sin opciones conserva los registros existentes y no
crea duplicados. `--force` elimina exclusivamente los registros con esos
prefijos y los vuelve a generar; no elimina los datos de demostración ni los
creados mediante las APIs:

```bash
./scripts/seed-all-20k.sh 20000 --force
```

## Verificación y evidencia

El verificador devuelve código distinto de cero si falta algún mínimo o si
encuentra relaciones SQL huérfanas:

```bash
./scripts/verify-seed-counts.sh
```

Salida esperada:

```text
OK PostgreSQL products=20000 orphan_products=0
OK PostgreSQL inventory_stock=20000 orphan_inventory=0 invalid_inventory=0
OK MySQL orders=20000 order_items=20000 orphan_items=0
OK MongoDB users=20000
```

Los conteos se limitan a los prefijos de la carga masiva. Por eso los datos de
demostración que crean los scripts de inicialización no alteran la evidencia.

Para detener los motores sin borrar la carga:

```bash
docker compose down
```

No use `docker compose down -v` si necesita conservar la evidencia, porque esa
opción elimina los volúmenes de las bases de datos.
