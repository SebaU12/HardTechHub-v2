# Consultas analíticas con Amazon Athena

Esta carpeta implementa la Fase 5 sobre la base Glue `hardtech_analytics`.

## Recursos

La plantilla `template.yaml` crea:

- workgroup `hardtech-workgroup` con Athena engine 3;
- resultados obligatorios en `s3://<bucket>/athena-results/`;
- cifrado SSE-S3;
- métricas de CloudWatch;
- límite de 100 MB escaneados por consulta para controlar costos del MVP;
- política IAM de lectura del catálogo y data lake, ejecución en el workgroup y escritura de resultados.

La política se crea sin adjuntarla a un usuario o rol. Adjunte el ARN mostrado por CloudFormation al rol EC2 o identidad que vaya a ejecutar las consultas. Athena usa los permisos del principal que llama al servicio para acceder a S3 y Glue.

## Orden de ejecución

Primero debe estar desplegada y validada la Fase 4:

```bash
cd infrastructure/glue
./deploy.sh hardtech-datalake us-east-1
./run-crawlers.sh us-east-1 hardtech_analytics
```

Después despliegue Athena:

```bash
cd ../athena
./deploy.sh hardtech-datalake us-east-1
```

El script comprueba el bucket, crea el marcador `athena-results/` y despliega el stack `hardtech-athena`. CloudFormation muestra al final el workgroup, la ubicación de resultados y el ARN de la política.

## Ejecutar todas las consultas

```bash
./run-queries.sh us-east-1 hardtech_analytics hardtech-workgroup
```

Las consultas se ejecutan en orden. El script espera mientras estén `QUEUED` o `RUNNING`, falla si Athena devuelve `FAILED` o `CANCELLED`, y muestra las primeras veinte filas de cada resultado. Los CSV completos quedan en el prefijo configurado por el workgroup.

El timeout predeterminado es de cinco minutos por consulta y puede ajustarse con `ATHENA_QUERY_TIMEOUT_SECONDS`.

## Consultas versionadas

| Archivo | Resultado |
|---|---|
| `01_event_count_by_type.sql` | Conteo combinado de los cinco dominios de eventos |
| `02_top_five_viewed_products.sql` | Cinco productos con más vistas |
| `03_sales_summary.sql` | Órdenes, ventas brutas y ticket promedio |
| `04_sales_by_category.sql` | Ventas por categoría cruzando PostgreSQL y MySQL |
| `05_high_views_low_sales.sql` | Comparación de interés y unidades vendidas |
| `06_most_failed_compatibility_rules.sql` | Reglas que fallan con mayor frecuencia |
| `07_compatible_build_rate.sql` | Porcentaje de builds compatibles |
| `08_user_registrations_by_day.sql` | Registros de usuarios por fecha |
| `09_view_compatibility_order_funnel.sql` | Embudo entre navegación, compatibilidad y compra |
| `10_inventory_summary.sql` | Resumen del snapshot de inventario más reciente |
| `11_inventory_low_stock.sql` | Productos bajo el mínimo en el snapshot más reciente |
| `12_inventory_event_activity.sql` | Actividad diaria por tipo de evento de inventario |
| `13_inventory_product_rotation.sql` | Unidades confirmadas y confirmaciones por producto |

Las consultas de snapshots filtran por el `snapshot_at` más reciente para no sumar varias exportaciones completas de la misma base operacional.

## Validación manual

```bash
aws athena get-work-group \
  --work-group hardtech-workgroup \
  --region us-east-1 \
  --query 'WorkGroup.Configuration.ResultConfiguration'

aws s3 ls s3://hardtech-datalake/athena-results/ --recursive
```

Para una consulta concreta:

```bash
EXECUTION_ID=$(aws athena start-query-execution \
  --query-string "SELECT count(*) FROM products" \
  --query-execution-context Database=hardtech_analytics \
  --work-group hardtech-workgroup \
  --query QueryExecutionId --output text)

aws athena get-query-execution --query-execution-id "$EXECUTION_ID"
```

## Solución de problemas

- `AccessDenied` en Athena: adjunte la política emitida por el stack al principal que ejecuta la consulta.
- `AccessDenied` en Glue o S3: compruebe que se usa el mismo bucket, región, cuenta y base configurados en las plantillas.
- `TABLE_NOT_FOUND`: despliegue la Fase 4 y ejecute ambos crawlers antes de las consultas.
- Cero filas: compruebe objetos y particiones con `infrastructure/glue/validate-catalog.sh`.
- Error de tipo en `payload`: vuelva a desplegar la plantilla Glue actualizada y ejecute `hardtech-events-crawler`.
- `Bytes scanned limit was exceeded`: el workgroup limita cada consulta a 100 MB para la demostración; filtre por particiones o cambie conscientemente el límite.
- Lake Formation activo: conceda `SELECT` y `DESCRIBE` al mismo principal IAM.

## Referencias oficiales

- [Configuración de workgroups](https://docs.aws.amazon.com/AWSCloudFormation/latest/TemplateReference/aws-properties-athena-workgroup-workgroupconfiguration.html)
- [Permisos de Athena para S3 y Glue](https://docs.aws.amazon.com/athena/latest/ug/security-iam-athena.html)
- [Control de acceso de Athena a S3](https://docs.aws.amazon.com/athena/latest/ug/s3-permissions.html)
