# AWS Glue Data Catalog

La plantilla de esta carpeta crea de forma idempotente la Fase 4:

- base `hardtech_analytics`;
- rol IAM asumible por Glue y limitado a lectura de `raw/events/` y `processed/snapshots/`;
- cuatro tablas Parquet y cinco tablas JSON con nombres estables;
- crawler `hardtech-snapshots-crawler` para snapshots;
- crawler `hardtech-events-crawler` para eventos;
- particiones `year`, `month` y `day` en todas las tablas.

Las tablas se declaran primero y los crawlers las usan como `CatalogTargets`. Esto evita que Glue derive nombres variables desde las carpetas y permite distinguir `orders` de `order_events`. Los crawlers actualizan las tablas y agregan particiones sin crear tablas duplicadas.

## Requisitos

- AWS CLI v2 autenticado en la cuenta del curso.
- Permisos para CloudFormation, Glue, IAM y lectura del bucket.
- El bucket debe existir y contener al menos un objeto en cada prefijo que se quiera validar.
- Los eventos de navegación nuevos deben estar en JSON Lines. Analytics conserva compatibilidad con los lotes JSON históricos.

Compruebe primero la identidad y región activas:

```bash
aws sts get-caller-identity
aws configure get region
```

## Despliegue

```bash
cd infrastructure/glue
./deploy.sh hardtech-datalake us-east-1
```

La operación crea o actualiza el stack `hardtech-glue-catalog`. Una segunda ejecución sin cambios no duplica recursos.

## Ejecutar y validar los crawlers

```bash
./run-crawlers.sh us-east-1 hardtech_analytics
```

El script espera ambos crawlers, exige estado `SUCCEEDED` y después comprueba:

- existencia de las nueve tablas;
- claves de partición `year`, `month`, `day`;
- cantidad de particiones registradas;
- ubicación S3 y primer campo detectado.

También puede ejecutar solo la validación:

```bash
./validate-catalog.sh us-east-1 hardtech_analytics
```

## Tablas

| Tabla | Formato | Ubicación relativa al bucket |
|---|---|---|
| `products` | Parquet | `processed/snapshots/products/` |
| `orders` | Parquet | `processed/snapshots/orders/` |
| `order_items` | Parquet | `processed/snapshots/order_items/` |
| `users` | Parquet | `processed/snapshots/users/` |
| `order_events` | JSON Lines | `raw/events/orders/` |
| `compatibility_events` | JSON Lines | `raw/events/compatibility/` |
| `catalog_events` | JSON Lines | `raw/events/catalog/` |
| `identity_events` | JSON Lines | `raw/events/identity/` |
| `navigation_events` | JSON Lines | `raw/events/navigation/` |

## Evidencia para la entrega

Después de ejecutar los crawlers en AWS, conserve:

```bash
aws glue get-tables --database-name hardtech_analytics \
  --query 'TableList[*].[Name,StorageDescriptor.Location]' --output table

aws glue get-partitions --database-name hardtech_analytics \
  --table-name products --query 'Partitions[*].Values' --output table
```

En la consola de Glue, capture la lista de tablas, el esquema de `products`, las particiones y el estado exitoso de ambos crawlers.

## Solución de problemas

- `AccessDenied`: revise que CloudFormation pueda crear el rol y que la cuenta no use una permission boundary obligatoria.
- Cero particiones: confirme que existen objetos directamente bajo rutas `year=.../month=.../day=.../` y vuelva a ejecutar el crawler.
- Esquema JSON inconsistente: no mezcle dominios en el mismo prefijo y compruebe que haya un evento JSON completo por línea.
- Bucket con SSE-KMS: agregue `kms:Decrypt` para la clave utilizada al rol del crawler.
- Lake Formation activo: otorgue al rol permisos de ubicación de datos y `DESCRIBE`/`ALTER` sobre la base y tablas.

Para eliminar únicamente estos recursos:

```bash
aws cloudformation delete-stack --stack-name hardtech-glue-catalog --region us-east-1
```

La eliminación del stack no borra objetos del bucket S3.

## Referencias oficiales

- [Usar tablas existentes como origen de un crawler](https://docs.aws.amazon.com/glue/latest/dg/define-crawler-choose-data-sources.html)
- [Cómo Glue detecta particiones](https://docs.aws.amazon.com/glue/latest/dg/add-crawler.html)
- [Propiedad CatalogTarget de CloudFormation](https://docs.aws.amazon.com/AWSCloudFormation/latest/TemplateReference/aws-properties-glue-crawler-catalogtarget.html)
