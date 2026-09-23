# Infraestructura local de HardTech Hub

Este directorio permite levantar únicamente las dependencias de datos del MVP. Es útil cuando las APIs se ejecutan desde el host durante el desarrollo. Para iniciar toda la plataforma se debe usar el [`docker-compose.yml` principal](../docker-compose.yml).

## Servicios incluidos

- PostgreSQL para `catalog-service`
- MySQL para `order-service`
- MongoDB para `identity-service`
- LocalStack con `S3` para productores de eventos, Analytics e ingestors

PostgreSQL, MySQL y MongoDB también son las fuentes de los extractores batch que generan snapshots Parquet en S3.

## Estructura

- `docker-compose.yml`: orquestacion local de infraestructura
- `postgres/init/01_catalog.sql`: esquema inicial y semilla de catalogo
- `mysql/init/01_orders.sql`: esquema inicial y semilla de ordenes
- `mongodb/init/01-users.js`: crea usuarios, índices y documento demo
- `localstack/init/01-bootstrap.sh`: crea el bucket S3
- `glue/`: plantilla CloudFormation y scripts para el Data Catalog en AWS
- `athena/`: workgroup, política IAM, runner y consultas analíticas versionadas
- `.env.example`: variables base sugeridas para los microservicios

## Requisitos

- Docker 24 o superior.
- Docker Compose 2.20 o superior.
- Puertos `5432`, `3306`, `27017` y `4566` disponibles.

## Levantar el entorno

```bash
docker compose -f infrastructure/docker-compose.yml up -d
docker compose -f infrastructure/docker-compose.yml ps
```

Para detenerlo sin eliminar los datos:

```bash
docker compose -f infrastructure/docker-compose.yml down
```

Para reiniciar por completo los datos locales:

```bash
docker compose -f infrastructure/docker-compose.yml down -v
docker compose -f infrastructure/docker-compose.yml up -d
```

> La opción `-v` elimina los volúmenes. Los scripts SQL, MongoDB y LocalStack se ejecutan durante la creación de volúmenes nuevos, no en cada reinicio.

## Servicios disponibles

- PostgreSQL: `localhost:5432`
- MySQL: `localhost:3306`
- MongoDB: `localhost:27017`
- LocalStack: `localhost:4566`

## Recursos creados automáticamente

- Bucket S3: `hardtech-datalake`
- Base MongoDB: `hardtech_identity`
- Colección MongoDB: `users`, con índices únicos `user_id` y `email`
- Usuario demo: `demo@hardtech.com` / `password123`
- Esquema y cinco productos semilla en PostgreSQL
- Esquema y una orden semilla en MySQL

## Conexión desde las APIs

El archivo [`.env.example`](.env.example) reúne las variables base. Desde procesos ejecutados en el host, los endpoints deben usar `localhost`; los valores `postgres`, `mysql`, `mongodb` y `localstack` solo se resuelven dentro de la red Docker.

No se recomienda levantar este Compose y el Compose principal a la vez: ambos administran la red `hardtech-net`, y los servicios de infraestructura duplicados pueden competir por nombres o puertos.

Para conocer los límites de cada almacén y los flujos de datos, consulte la [documentación de arquitectura](../docs/ARCHITECTURE.md).

LocalStack se usa únicamente para S3 durante el desarrollo, pero no valida Glue. La Fase 4 debe desplegarse en la cuenta AWS del curso siguiendo la [guía de Glue](glue/README.md).

Athena tampoco se emula en el entorno local. Después de poblar Glue, continúe con la [guía de Athena](athena/README.md).
