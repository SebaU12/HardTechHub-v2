# Analytics Service

API FastAPI que expone resultados analíticos con dos modos de ejecución.

## Backends

### `ANALYTICS_BACKEND=s3`

Modo predeterminado de desarrollo. Lee todos los JSON bajo `S3_EVENTS_PREFIX`, incluyendo lotes JSON históricos y JSON Lines. El listado usa paginación S3. En este modo están disponibles:

- `GET /api/analytics/events/count`
- `GET /api/analytics/top-products`

Los demás endpoints responden `503` porque requieren las tablas relacionales catalogadas por Glue.

### `ANALYTICS_BACKEND=athena`

Ejecuta las consultas SQL versionadas de `infrastructure/athena/queries/`. El nombre de consulta se selecciona mediante un mapa interno; la API no acepta fragmentos SQL ni nombres de tabla proporcionados por el cliente.

Variables:

```dotenv
ANALYTICS_BACKEND=athena
AWS_DEFAULT_REGION=us-east-1
ATHENA_DATABASE=hardtech_analytics
ATHENA_WORKGROUP=hardtech-workgroup
ATHENA_OUTPUT_LOCATION=s3://hardtech-datalake/athena-results/
ATHENA_QUERY_TIMEOUT_SECONDS=30
ATHENA_POLL_INTERVAL_SECONDS=0.5
```

En AWS no configure access keys ni endpoints locales. Asocie a EC2 el rol que tenga adjunta la política `QueryPolicyArn` generada por el stack de Athena.

## Endpoints

| Endpoint | S3 | Athena |
|---|:---:|:---:|
| `/api/analytics/events/count` | Sí | Sí |
| `/api/analytics/top-products` | Sí | Sí |
| `/api/analytics/sales/summary` | — | Sí |
| `/api/analytics/sales/by-category` | — | Sí |
| `/api/analytics/products/conversion` | — | Sí |
| `/api/analytics/compatibility/failure-rules` | — | Sí |
| `/api/analytics/compatibility/summary` | — | Sí |
| `/api/analytics/users/registrations` | — | Sí |
| `/api/analytics/funnel` | — | Sí |

Las respuestas Athena incluyen `backend`, `query_execution_id` y `duration_ms`. Los decimales se devuelven como strings para no perder precisión en JSON.

## Manejo de ejecución

El servicio:

1. inicia la consulta en la base y workgroup configurados;
2. espera únicamente `QUEUED` y `RUNNING`;
3. procesa `SUCCEEDED`, `FAILED` y `CANCELLED`;
4. cancela la consulta al superar el timeout;
5. pagina todas las filas y convierte enteros, flotantes y booleanos;
6. registra nombre, execution ID, duración y cantidad de filas.

Los fallos de AWS se traducen a `502`; los timeouts a `504`; una configuración inválida a `500`.

## Pruebas

Desde la raíz:

```bash
docker compose build analytics-service
docker compose run --rm --no-deps analytics-service \
  python -m unittest discover -s tests -v
```

Las pruebas no necesitan AWS: utilizan un cliente Athena simulado para comprobar estados, timeout, cancelación, paginación, tipos, respuestas HTTP y OpenAPI.
