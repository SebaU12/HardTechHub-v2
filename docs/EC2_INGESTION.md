# Ejecución de los extractores batch en EC2

Esta guía despliega únicamente los procesos de ingesta de la Fase 3. Los tres extractores comparten una imagen Docker y cambian el comando de inicio. Pueden ejecutarse manualmente o permanecer activos con un intervalo configurable.

## 1. Requisitos

- Una instancia EC2 con Docker y Docker Compose.
- Acceso de red desde la instancia hacia PostgreSQL y MySQL.
- Un rol IAM asociado a EC2; no se deben copiar access keys dentro de la imagen.
- El repositorio disponible en la instancia.
- Acceso privado a MongoDB desde Identity Ingestor.

El rol necesita, como mínimo, `s3:PutObject` sobre `arn:aws:s3:::<bucket>/processed/snapshots/*`. El acceso a PostgreSQL, MySQL y MongoDB se controla con credenciales propias y reglas de red; Identity Ingestor usa un usuario MongoDB de solo lectura.

## 2. Configuración

En AWS no se define `S3_ENDPOINT_URL`: boto3 utiliza S3 real mediante el rol de la instancia. Configure el resto de las variables en un archivo protegido fuera del repositorio, por ejemplo `/opt/hardtech/ingestion.env`:

```dotenv
AWS_DEFAULT_REGION=us-east-1
S3_BUCKET=hardtech-datalake
RUN_ONCE=true
SNAPSHOT_INTERVAL_SECONDS=3600

POSTGRES_HOST=<host-postgresql>
POSTGRES_PORT=5432
POSTGRES_DB=hardtech_catalog
POSTGRES_USER=<usuario-lectura>
POSTGRES_PASSWORD=<secreto>

MYSQL_HOST=<host-mysql>
MYSQL_PORT=3306
MYSQL_DATABASE=hardtech_orders
MYSQL_USER=<usuario-lectura>
MYSQL_PASSWORD=<secreto>

MONGODB_URI=mongodb://<usuario-lectura>:<secreto>@<host-privado>:27017/hardtech_identity?authSource=hardtech_identity
MONGODB_DATABASE=hardtech_identity
MONGODB_USERS_COLLECTION=users
MONGODB_BATCH_SIZE=1000
```

Use usuarios de base de datos con permisos `SELECT` solamente. El directorio y el archivo de variables deben ser legibles solo por el usuario que ejecuta Docker.

## 3. Construcción

Desde la raíz del repositorio:

```bash
docker build -t hardtech-ingestion:latest ingestion/
```

## 4. Ejecución única

```bash
docker run --rm --env-file /opt/hardtech/ingestion.env \
  -e S3_OUTPUT_PREFIX=processed/snapshots/products/ \
  hardtech-ingestion:latest python catalog_ingestor.py

docker run --rm --env-file /opt/hardtech/ingestion.env \
  -e S3_ORDERS_PREFIX=processed/snapshots/orders/ \
  -e S3_ORDER_ITEMS_PREFIX=processed/snapshots/order_items/ \
  hardtech-ingestion:latest python orders_ingestor.py

docker run --rm --env-file /opt/hardtech/ingestion.env \
  -e S3_OUTPUT_PREFIX=processed/snapshots/users/ \
  hardtech-ingestion:latest python identity_ingestor.py
```

Cada ejecución termina con código distinto de cero si la lectura o la carga falla, y registra en stdout el número de filas y la clave S3 creada.

## 5. Ejecución periódica

Cambie `RUN_ONCE=false` y ajuste `SNAPSHOT_INTERVAL_SECONDS`. Ejecute cada contenedor con un nombre y política de reinicio:

```bash
docker run -d --name catalog-ingestor --restart unless-stopped \
  --env-file /opt/hardtech/ingestion.env \
  -e RUN_ONCE=false \
  -e S3_OUTPUT_PREFIX=processed/snapshots/products/ \
  hardtech-ingestion:latest python catalog_ingestor.py
```

Repita el patrón para `orders_ingestor.py` e `identity_ingestor.py`. Para una demostración corta también puede usar los servicios incluidos en el `docker-compose.yml` raíz.

## 6. Verificación

```bash
docker logs catalog-ingestor
aws s3 ls s3://hardtech-datalake/processed/snapshots/ --recursive
```

Una segunda ejecución debe crear otra clave. La ruta lleva particiones `year`, `month` y `day`, y el nombre contiene la hora UTC más un sufijo aleatorio.
