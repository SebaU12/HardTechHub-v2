# Guía de pruebas y demostración

Esta guía permite repetir la Fase 7 sin preparar datos manualmente. La parte
local valida el flujo de negocio, la publicación de eventos, los snapshots
Parquet y Analytics sobre S3/LocalStack. Glue y Athena se validan después en la
cuenta AWS del curso porque LocalStack no emula esos servicios en este proyecto.

## 1. Pruebas automatizadas

Requisitos: Docker, Docker Compose y la red `hardtech-net` (el script la crea si
no existe).

```bash
./scripts/test-phase7.sh
```

La construcción de las imágenes ejecuta 25 pruebas:

| Componente | Casos | Cobertura principal |
|---|---:|---|
| Identity | 5 | eventos, inserción MongoDB, duplicados y login por índice |
| Catalog | 2 | sobre, serialización y partición UTC |
| Orders | 1 | evento de orden y clave S3 |
| Compatibility | 2 | resultado, identificador y clave S3 |
| Ingestion | 3 | sanitización MongoDB, claves únicas y Parquet legible |
| Analytics | 12 | estados, timeout, paginación, tipos, errores y OpenAPI |

El resultado esperado termina con:

```text
Fase 7: todas las pruebas incluidas en las imágenes finalizaron correctamente.
```

## 2. Demostración local integral

```bash
./scripts/demo-local.sh
```

El script crea datos con identificadores únicos y ejecuta en orden:

1. registro de usuario y evento `USER_REGISTERED` sanitizado;
2. consulta y actualización de producto;
3. validación de un build compatible;
4. validación de un build incompatible;
5. creación de una orden;
6. transición de la orden a `PAID`;
7. extracción de productos, órdenes, ítems y usuarios a Parquet;
8. validación de esquemas, particiones y exclusión de datos sensibles;
9. listado de objetos del data lake;
10. consulta de conteo a Analytics con backend S3.

Los contenedores se eliminan al finalizar y los volúmenes se conservan. Para
dejar la plataforma levantada después de la prueba:

```bash
KEEP_RUNNING=1 ./scripts/demo-local.sh
```

La salida sirve como evidencia textual: muestra las respuestas JSON, las claves
raw, las particiones Parquet, el número de filas y los logs de cada extractor.
Para la entrega puede capturarse esa terminal junto con la consola AWS indicada
en la siguiente sección.

## 3. Glue, Athena y Analytics en AWS

Antes de ejecutar esta parte deben cumplirse estas condiciones:

- credenciales válidas disponibles para AWS CLI;
- eventos y snapshots cargados en el bucket real;
- Analytics desplegado con `ANALYTICS_BACKEND=athena`;
- URL accesible del Analytics Service.

```bash
./scripts/demo-aws.sh hardtech-datalake https://URL-ANALYTICS us-east-1
```

El script verifica la identidad AWS, despliega Glue, ejecuta ambos crawlers,
despliega el workgroup de Athena, exige que las nueve consultas terminen en
`SUCCEEDED` y consulta los nueve endpoints de Analytics.

Si el bucket tiene otro nombre, reemplácese `hardtech-datalake`. Los scripts son
idempotentes y reutilizan los stacks CloudFormation existentes.

## 4. Evidencias de entrega

- terminal de `test-phase7.sh` sin fallos;
- listado S3 con `raw/events/<dominio>/year=...` y
  `processed/snapshots/<dataset>/year=...`;
- logs `Uploaded dataset=... rows=...` de los tres extractores;
- tablas y particiones visibles en Glue Data Catalog;
- una ejecución Athena con estado `SUCCEEDED` y su resultado;
- respuesta JSON de un endpoint Analytics mostrando `backend: athena`;
- diagrama final de [arquitectura](ARCHITECTURE.md).

Los tres puntos relacionados con Glue, Athena y el backend `athena` no deben
darse por aprobados hasta ejecutarlos con la cuenta del curso.
