# Costos y controles del MVP

HardTech Hub usa un pipeline serverless para que el costo dependa del uso. No
se fija un total en dólares porque la tarifa cambia según región, fecha, clase
de almacenamiento y cuenta. Antes de la demostración debe revisarse la
[calculadora de AWS](https://calculator.aws/).

## Componentes facturables

| Servicio | Qué genera costo | Control aplicado en el proyecto |
|---|---|---|
| S3 | GB-mes, PUT/LIST/GET y transferencia aplicable | Archivos pequeños, misma región y prefijos separados |
| Glue Data Catalog | Objetos y solicitudes de metadatos | Solo 1 base, 9 tablas y sus particiones |
| Glue Crawlers | DPU-tiempo por ejecución, con mínimo facturable | Ejecución manual para la demostración |
| Athena | Datos escaneados por consulta y resultados S3 | Parquet, particiones y límite de 100 MB por consulta |
| CloudWatch | Métricas/logs que excedan capas gratuitas aplicables | Solo métricas del workgroup y logs operativos |
| EC2/ALB | Tiempo, tamaño, almacenamiento y tráfico | Detener o eliminar al terminar; ALB opcional |
| MongoDB en EC2 | Parte de cómputo y disco de la VM privada | Colección e índices pequeños para el MVP |

AWS publica que Athena SQL bajo demanda cobra por bytes analizados, con redondeo
y mínimo por consulta; comprimir, usar Parquet y filtrar particiones reduce el
escaneo. El workgroup de este repositorio cancela cualquier consulta que intente
superar 100 MB. Consulte la [tarifa oficial de Athena](https://aws.amazon.com/athena/pricing/).

Glue cobra los crawlers según DPU-tiempo. El Data Catalog ofrece un volumen
inicial de objetos y solicitudes sin costo, pero depende de las condiciones
vigentes de la cuenta. Consulte la [tarifa oficial de Glue](https://aws.amazon.com/glue/pricing/).

S3 cobra almacenamiento y solicitudes; incluso navegar por la consola produce
solicitudes. Revise la [tarifa oficial de S3](https://aws.amazon.com/s3/pricing/).

## Estimación reproducible

Registre estas métricas después de una demo:

```bash
aws s3 ls s3://<bucket>/ --recursive --summarize
aws glue get-crawler --name hardtech-snapshots-crawler \
  --query 'Crawler.LastCrawl'
aws glue get-crawler --name hardtech-events-crawler \
  --query 'Crawler.LastCrawl'
aws athena get-query-runtime-statistics --query-execution-id <id>
```

El costo aproximado se obtiene así:

```text
S3       = almacenamiento + solicitudes + transferencia aplicable
Glue     = tiempo facturable de ambos crawlers + catálogo fuera de cuota incluida
Athena   = bytes escaneados facturables × tarifa regional
Compute  = horas EC2 + EBS + horas/capacidad de ALB si se utiliza
```

## Medidas para evitar cargos inesperados

- ejecutar crawlers solo cuando cambien particiones;
- conservar el corte de 100 MB del workgroup;
- no usar `SELECT *` fuera de verificaciones pequeñas;
- consultar `year`, `month` y `day` siempre que sea posible;
- borrar resultados Athena y snapshots de prueba cuando termine la evaluación;
- detener EC2 y eliminar ALB si no se usarán;
- crear un AWS Budget o alerta de facturación para la cuenta del curso;
- revisar Cost Explorer al día siguiente, porque algunos cargos no aparecen de inmediato.

La eliminación está documentada en [Despliegue AWS](AWS_DEPLOYMENT.md#10-eliminación).
