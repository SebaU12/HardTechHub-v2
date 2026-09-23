# Troubleshooting

## Diagnóstico rápido

```bash
docker compose ps
docker compose logs --tail=100 <servicio>
curl --fail http://localhost:8001/health
curl --fail http://localhost:8005/health
aws sts get-caller-identity
```

No mezcle endpoints LocalStack con credenciales AWS. En AWS debe omitirse
`S3_ENDPOINT_URL`; MongoDB siempre usa su URI privada propia.

## Docker y servicios locales

### La red `hardtech-net` no existe

```bash
docker network create hardtech-net
```

### Una base está saludable pero no contiene semillas nuevas

Los scripts de inicialización solo se ejecutan al crear el volumen. Para borrar
intencionalmente el estado local y recrearlo:

```bash
docker compose down -v
docker compose up -d --build
```

`down -v` elimina PostgreSQL, MySQL, MongoDB y S3 locales.

### Orders o Compatibility devuelve 502/503

Compruebe `catalog-service`, su health check y `CATALOG_SERVICE_URL`. Estos dos
servicios dependen síncronamente de Catalog.

### Una operación termina pero `event_published` es `false`

La escritura operacional ya fue confirmada. Revise LocalStack/S3, bucket,
prefijo y permisos. El MVP no tiene outbox, por lo que debe repetirse la
operación o generar el evento de forma controlada para la demo.

## S3 y snapshots

### No aparecen objetos

Compruebe bucket, región, endpoint y prefijo:

```bash
aws s3api head-bucket --bucket <bucket>
aws s3 ls s3://<bucket>/ --recursive
```

En local utilice `docker compose exec localstack awslocal ...`.

### El extractor falla al conectar

Desde Docker use hosts `postgres`, `mysql` y `localstack`; desde el host use
`localhost`. En EC2 valide rutas, security groups y usuarios SQL de lectura.

### Parquet tiene tipos incorrectos

Ejecute `python validate_data_lake.py` desde la imagen de ingesta. No convierta
montos a `float`: los esquemas esperan `decimal128(10,2)` y timestamps UTC.

## Glue y particiones

### `AccessDenied`

Valide el rol del crawler, el bucket exacto y su región. Si usa SSE-KMS agregue
acceso a la clave. Si Lake Formation administra el catálogo, conceda permisos
de ubicación y `DESCRIBE`/`ALTER`.

### El crawler termina, pero hay cero particiones

Los objetos deben estar directamente bajo rutas Hive:

```text
<dataset>/year=YYYY/month=MM/day=DD/archivo
```

Verifique mayúsculas, ceros del mes/día y que el crawler apunte al prefijo de la
tabla. Después repita:

```bash
./infrastructure/glue/run-crawlers.sh us-east-1 hardtech_analytics
```

### Esquema JSON incorrecto o `HIVE_BAD_DATA`

No mezcle dominios en un prefijo. Cada línea debe ser un JSON completo y el
tipo del `payload` debe coincidir con `catalog.yaml`. Identifique el objeto con
Athena o S3, corríjalo y vuelva a ejecutar el crawler.

### Se crean nombres de tabla inesperados

Use la plantilla actual. Sus crawlers emplean `CatalogTargets` sobre nueve
tablas predefinidas; no cambie a un target S3 genérico para este MVP.

## Athena

### `TABLE_NOT_FOUND`

Confirme cuenta, región, base `hardtech_analytics` y ejecución de los dos
crawlers. Ejecute `infrastructure/glue/validate-catalog.sh`.

### `GENERIC_INTERNAL_ERROR` o cero filas

Revise que las particiones estén registradas y que la ubicación Glue corresponda
al bucket real. Pruebe primero `SELECT count(*) FROM products`.

### `Bytes scanned limit was exceeded`

El límite de 100 MB es intencional. Restrinja particiones/columnas o reduzca los
datos de demo. Solo modifique el límite conscientemente en `template.yaml`.

### Resultados no escribibles

El principal necesita escritura en `athena-results/*`, y el bucket no debe
bloquearlo mediante una bucket policy o clave KMS incompatible. Adjunte la
política `QueryPolicyArn` emitida por CloudFormation.

## Analytics con Athena

### `/health` funciona pero las consultas devuelven 500/502/504

Compruebe `ANALYTICS_BACKEND=athena`, región, base, workgroup, output location y
rol IAM. `504` indica timeout; revise el estado real con
`aws athena get-query-execution` antes de aumentarlo.

### Analytics sigue mostrando `backend: s3`

La variable se lee al iniciar el proceso. Recree el contenedor después de
cambiarla y no reutilice la configuración local del Compose sin sobrescribirla.

## Evidencia insuficiente

Una captura de la consola no sustituye la validación. Guarde también la salida
de `validate-catalog.sh`, `run-queries.sh`, el listado S3 y una respuesta JSON de
Analytics. La secuencia completa está en [DEMO.md](DEMO.md).
