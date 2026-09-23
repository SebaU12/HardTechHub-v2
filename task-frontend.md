# Plan de actualización del frontend de HardTech Hub

## Objetivo

Actualizar el frontend existente para que funcione como interfaz de demostración
del backend actual de HardTech Hub desplegado en AWS.

El frontend debe permitir demostrar, desde una interfaz coherente y visual, los
flujos principales ya disponibles en API Gateway:

- registro, acceso y consulta del perfil;
- consulta y búsqueda del catálogo;
- carrito y creación de pedidos;
- comprobación de compatibilidad de componentes;
- consulta de los resultados analíticos producidos con S3, Glue y Athena.

La identidad visual actual se conservará. El trabajo se concentra en actualizar
contratos, integrar las capacidades nuevas del backend y preparar una demo
estable.

## Prioridad del proyecto

El backend y la arquitectura cloud son el núcleo del trabajo universitario. El
frontend sirve como cliente de presentación y como evidencia visual de que los
microservicios, API Gateway, ALB, bases de datos y consultas analíticas funcionan
de extremo a extremo.

Por ello se prioriza:

1. integración funcional con las APIs actuales;
2. claridad durante la exposición;
3. manejo correcto de cargas, errores y respuestas vacías;
4. conservación del diseño existente;
5. una ejecución y configuración reproducibles.

## Fuera de alcance

- autorización avanzada por roles;
- endurecimiento de JWT, cookies `HttpOnly` o rotación de tokens;
- panel administrativo completo;
- pagos reales;
- recuperación de contraseña y verificación de correo;
- SEO y optimización productiva avanzada;
- reemplazo completo del sistema visual existente;
- streaming o actualización analítica en tiempo real.

## Backend objetivo

En AWS, todas las peticiones se realizan mediante un único endpoint público:

```text
https://s7d3vxbohi.execute-api.us-east-1.amazonaws.com
```

API Gateway enruta internamente hacia el ALB y los cinco microservicios. La URL
debe suministrarse mediante una variable de entorno; no debe quedar fija en el
código fuente.

### Dominios disponibles

| Dominio | Prefijo |
|---|---|
| Identity | `/api/auth` |
| Catalog | `/api/products` |
| Orders | `/api/orders` |
| Compatibility | `/api/compatibility` |
| Analytics | `/api/analytics` |

## Arquitectura del frontend

Se mantiene el flujo actual:

```text
Página o componente
        │
        ▼
Hook de estado
        │
        ▼
Servicio tipado
        │
        ▼
Cliente Axios
        │
        ▼
API Gateway
```

## Lineamientos visuales que deben conservarse

- fondo oscuro y superficies jerarquizadas;
- naranja `#ff6b00` como color de énfasis;
- tipografía Manrope;
- encabezados compactos y de alto contraste;
- hero y bloques editoriales de tecnología;
- tarjetas modulares de productos;
- barra superior, header, navegación, contenido y footer;
- estados de carga mediante skeletons;
- estados vacíos y errores visibles;
- comportamiento responsive;
- foco de teclado, textos alternativos y etiquetas accesibles.

Los cambios visuales deben extender el lenguaje existente, no introducir un
segundo sistema de diseño.

---

## Fase 0: establecer la línea base

### Tareas

- [x] Instalar dependencias con el lockfile mediante `npm ci`.
- [x] Ejecutar `npm test`, `npm run lint` y `npm run build` antes de modificar.
- [x] Registrar cualquier error preexistente.
- [x] Confirmar las rutas actuales del frontend y sus estados protegidos.
- [x] Confirmar en API Gateway los contratos usados por la interfaz.
- [x] Retirar el `console.log` de la página de producto.

### Criterio de aceptación

- [x] Existe una línea base reproducible de pruebas, lint y build.
- [x] Se conocen los fallos preexistentes y no se atribuyen a la actualización.

### Resultado de la línea base

Validación realizada el 23 de septiembre de 2026 con Node.js 24.13.0 y npm
11.6.2:

- `npm ci`: 202 paquetes instalados y 0 vulnerabilidades reportadas;
- `npm test`: 1 archivo de integración aprobado, 0 fallos;
- la primera ejecución de `npm run lint` detectó cinco imports sin uso en
  `AuthForm`, `Hero` y `Header`;
- la primera ejecución de `npm run build` falló por esos mismos cinco imports;
- los imports preexistentes fueron retirados como limpieza mínima de la línea
  base;
- se retiró el `console.log(product)` de `ProductPage`;
- después de la limpieza, `npm test`, `npm run lint` y `npm run build`
  terminaron con código cero;
- las rutas públicas confirmadas son inicio, catálogo, detalle de producto,
  carrito, login, registro y ayuda;
- las rutas protegidas confirmadas son checkout, pedidos, detalle de pedido y
  perfil;
- los servicios existentes coinciden con los endpoints actuales de Identity,
  Catalog y Orders, mientras Compatibility y siete consultas de Analytics
  permanecen pendientes para sus fases correspondientes.

## Fase 1: configurar un único acceso a API Gateway

### Tareas

- [x] Agregar `VITE_API_BASE_URL` a los tipos de entorno.
- [x] Actualizar `.env.example` con una configuración local y un ejemplo AWS.
- [x] Crear los clientes de Identity, Catalog, Orders, Compatibility y Analytics
  usando la misma base en producción.
- [x] Mantener los proxies separados de Vite para desarrollo local.
- [x] Agregar el proxy de `/api/compatibility`.
- [x] Mantener soporte temporal para las variables antiguas si facilita la
  ejecución local.
- [x] Centralizar el timeout y el tratamiento básico de errores HTTP.
- [x] Permitir un timeout mayor para consultas Athena que para operaciones
  ordinarias.

### Configuración esperada en AWS

```dotenv
VITE_API_BASE_URL=https://s7d3vxbohi.execute-api.us-east-1.amazonaws.com
```

### Criterios de aceptación

- [x] El frontend consume los cinco servicios mediante API Gateway.
- [x] No contiene URLs de instancias EC2, ALB interno ni IP privadas.
- [x] La ejecución local continúa admitiendo servicios en puertos separados.

### Resultado

Implementado el 23 de septiembre de 2026:

- `VITE_API_BASE_URL` quedó como configuración preferida para AWS;
- `.env.production.example` apunta al endpoint público de API Gateway;
- el `.env` local ignorado por Git quedó configurado con ese mismo endpoint para
  ejecutar la demo directamente;
- las cinco instancias Axios comparten la base configurada y reciben el token de
  sesión;
- las variables separadas y los proxies por puerto continúan disponibles para
  desarrollo local;
- Compatibility utiliza el puerto local 8004;
- las APIs operacionales usan un timeout de 15 segundos y Analytics uno de 60;
- `getApiErrorMessage` continúa centralizando la presentación de fallos HTTP;
- pruebas, lint y build terminaron con código cero;
- un build de producción confirmó la URL de API Gateway en el bundle y la
  ausencia de IP privadas o del DNS del ALB interno.

## Fase 2: actualizar contratos TypeScript

### Identity

- [x] Representar `event_published` y `event_key` en la respuesta de registro.
- [x] Mantener los contratos actuales de login y perfil.

### Catalog

- [x] Verificar los campos reales de lista y detalle de producto.
- [x] Representar `event_published` y `event_key` en las operaciones que publican
  eventos.
- [x] Normalizar IDs como números y precios como strings decimales.

### Orders

- [x] Actualizar `CreateOrderResponse` con `event_published` y `event_key`.
- [x] Mantener separados los tipos de orden, ítems y detalle de orden.
- [x] Representar estados con una unión de strings conocida.

### Compatibility

- [x] Crear los tipos de request para `user_id`, `session_id` y componentes.
- [x] Crear los tipos de respuesta para `compatible`, `checks`, `rule`, `status`
  y `details`.
- [x] Incluir `event_published` y `event_key`.

### Analytics

- [x] Corregir `product_id` para que coincida con la respuesta numérica actual.
- [x] Eliminar campos heredados que ya no devuelve Analytics.
- [x] Tipar `backend`, `query_execution_id` y `duration_ms`.
- [x] Crear contratos para los nueve endpoints analíticos.
- [x] Mantener importes como strings cuando Athena los devuelve como decimales.

### Criterios de aceptación

- [x] Las respuestas observadas en AWS se pueden representar sin conversiones
  implícitas incorrectas.
- [x] `npm run build` no presenta errores de TypeScript.

### Resultado

Implementado el 23 de septiembre de 2026:

- se creó un contrato común para las respuestas que publican eventos en S3;
- registro, creación de producto, desactivación, creación de orden y cambio de
  estado representan `event_key` como nullable;
- la actualización de producto representa correctamente su arreglo
  `event_keys`;
- los pedidos mantienen tipos separados para cabecera, ítems y detalle;
- Compatibility representa los cinco tipos de componente, las tres reglas y los
  estados `PASS`/`FAIL` de la implementación Go desplegada;
- Analytics representa conteo de eventos, productos vistos, resumen de ventas,
  ventas por categoría, conversión, reglas fallidas, resumen de compatibilidad,
  registros y funnel;
- los conteos e IDs se tipan como números y los importes `DECIMAL` de Athena
  como strings;
- `npm test`, `npm run lint` y `npm run build` terminaron con código cero.

## Fase 3: adaptar el catálogo a la carga de demostración

La base contiene más de 20,000 productos de prueba. La interfaz no debe intentar
renderizar miles de tarjetas simultáneamente.

### Tareas mínimas de frontend

- [x] Compartir o almacenar en caché la consulta del catálogo para evitar que
  Home, Header y Catalog descarguen independientemente el mismo conjunto.
- [x] Mostrar un número limitado de productos por página.
- [x] Agregar paginación visible con página actual y navegación anterior/siguiente.
- [x] Aplicar búsqueda, categoría, marca y ordenamiento antes de paginar.
- [x] Reiniciar la página actual cuando cambien los filtros.
- [x] Limitar a cinco las sugerencias del buscador del header.
- [x] Evitar renderizar todas las tarjetas ocultándolas sólo mediante CSS.
- [x] Mantener skeleton, reintento, estado vacío y fallback de imagen.

### Mejora opcional del backend

Si la descarga completa afecta la demo, agregar parámetros compatibles sin
romper el endpoint actual:

```http
GET /api/products?page=1&page_size=24&search=ryzen&category=CPU&brand=AMD
```

La respuesta paginada debería incluir `items`, `page`, `page_size`, `total` y
`total_pages`. Esta mejora es opcional para la primera demo del frontend.

### Categorías

- [x] Alinear la navegación con las categorías disponibles: CPU, GPU,
  Motherboard, RAM y PSU.
- [x] Evitar enlaces destacados hacia categorías sin datos como Laptop o Monitor.
- [x] Conservar la estructura para reactivarlas si después se agregan productos.

### Criterios de aceptación

- [x] La página de catálogo permanece utilizable con los datos sembrados.
- [x] Nunca se montan 20,000 tarjetas en el DOM.
- [x] Buscar y filtrar presenta resultados coherentes.
- [x] Home y Header no generan descargas redundantes innecesarias.

### Resultado

Implementado el 23 de septiembre de 2026:

- `ProductsProvider` realiza una sola consulta compartida para Header, Home y
  Catalog;
- la búsqueda, los filtros y el ordenamiento se aplican antes de dividir los
  resultados;
- cada página monta como máximo 24 tarjetas y conserva los filtros en la URL;
- cambiar búsqueda, categoría, marca, precio u ordenamiento vuelve a la primera
  página;
- la paginación muestra rango, página actual, total y botones anterior/siguiente;
- las sugerencias globales se detienen después de encontrar cinco coincidencias;
- la navegación, las grillas y el hero sólo destacan CPU, GPU, Motherboard, RAM
  y PSU;
- la paginación de servidor permanece como mejora opcional si el tamaño de la
  transferencia completa afecta una futura demo;
- se agregaron pruebas de filtrado, ordenamiento, paginación y sugerencias;
- `npm test`, `npm run lint` y `npm run build` terminaron con código cero.

## Fase 4: completar el flujo de identidad y carrito

### Tareas

- [x] Validar registro, login y perfil contra API Gateway.
- [x] Conservar el usuario autenticado durante una recarga usando
  `sessionStorage` y `/api/auth/me`.
- [x] Limpiar la sesión almacenada al cerrar sesión o recibir un 401.
- [x] Mantener el carrito asociado al usuario activo.
- [x] Mostrar mensajes comprensibles para credenciales incorrectas, duplicados y
  fallos de red.
- [x] Evitar dobles envíos mientras una mutación está en curso.

### Criterios de aceptación

- [x] Un usuario puede registrarse, iniciar sesión, recargar y consultar su perfil.
- [x] Cambiar de usuario no conserva el carrito del usuario anterior.
- [x] Los errores del backend se muestran sin exponer trazas técnicas.

### Resultado

Implementado y validado el 23 de septiembre de 2026:

- el JWT se guarda en `sessionStorage` sólo después de obtener correctamente el
  perfil;
- al recargar, el provider restaura el header Bearer y valida el token mediante
  `/api/auth/me` antes de resolver las rutas protegidas;
- logout, token inválido y respuesta 401 eliminan el token almacenado y el header
  de todos los clientes;
- si `sessionStorage` está bloqueado, la sesión en memoria continúa funcionando;
- el `CartProvider` se monta con la clave del `user_id`, por lo que un cambio de
  cuenta nunca reutiliza el carrito anterior;
- login, registro y las mutaciones existentes bloquean envíos simultáneos;
- se agregaron mensajes en español para credenciales incorrectas, cuenta
  duplicada, token vencido y fallos de conexión;
- se actualizó el contenido visual que antes afirmaba que la sesión se perdía al
  recargar;
- API Gateway registró `frontend_phase4_20260923@hardtech.com`, publicó su evento,
  entregó un token y devolvió correctamente el perfil autenticado;
- el JWT usado en la comprobación se mantuvo fuera de la salida y se eliminó al
  finalizar;
- `npm test`, `npm run lint` y `npm run build` terminaron con código cero.

## Fase 5: validar pedidos de extremo a extremo

### Tareas

- [x] Mantener agregar, quitar y cambiar cantidades en el carrito.
- [x] Mostrar subtotal y total antes de confirmar.
- [x] Crear la orden mediante `POST /api/orders`.
- [x] Mostrar `order_id`, estado, total y productos en la confirmación.
- [x] Mostrar el historial de pedidos del usuario.
- [x] Permitir abrir el detalle de una orden.
- [x] Mostrar visualmente si el evento `ORDER_CREATED` fue publicado.
- [x] Conservar el carrito si la creación falla y limpiarlo sólo al confirmarse.

### Criterios de aceptación

- [x] El flujo catálogo → carrito → checkout → detalle funciona mediante API
  Gateway.
- [x] La orden creada aparece en el historial.
- [x] La interfaz confirma que el backend publicó el evento para el data lake.

### Resultado

Implementado y validado el 23 de septiembre de 2026:

- el carrito conserva agregar, quitar y modificar cantidades;
- checkout muestra subtotal, IGV estimado de 18 %, envío estimado de S/ 25 y
  total antes de confirmar;
- el cálculo visual está aislado en `calculateOrderEstimate` y coincide con las
  reglas actuales de Orders;
- la respuesta completa de creación se transporta al detalle antes de limpiar
  el carrito;
- el carrito sólo se limpia después de que `POST /api/orders` responde
  correctamente; ante un error permanece intacto;
- la confirmación muestra ID, estado, total, productos y resultado de publicación
  de `ORDER_CREATED`;
- una publicación fallida se diferencia visualmente sin afirmar que la orden
  también falló;
- API Gateway creó la orden `32771` para `frontend_phase4_20260923`, con estado
  `PENDING` y total `1794.88`;
- la respuesta confirmó `event_published: true` y una clave bajo
  `raw/events/orders/`;
- la orden apareció en el historial y su detalle devolvió el producto 1, cantidad
  1, precio unitario `1499.90` y subtotal `1499.90`;
- el JWT de validación permaneció fuera de la salida y los archivos temporales se
  eliminaron al finalizar;
- `npm test`, `npm run lint` y `npm run build` terminaron con código cero.

## Fase 6: incorporar el comprobador de compatibilidad

### Diseño funcional

Agregar una ruta pública:

```text
/compatibilidad
```

La página permitirá elegir productos para los tipos soportados:

- CPU;
- motherboard;
- RAM;
- GPU;
- PSU.

### Tareas

- [x] Crear `compatibilityServices.ts`.
- [x] Crear un hook de mutación para ejecutar la comprobación.
- [x] Agregar la ruta y un enlace visible en la navegación.
- [x] Reutilizar los productos del catálogo para los selectores.
- [x] Enviar `user_id` cuando exista sesión y generar un `session_id` de demo.
- [x] Mostrar el resultado global como compatible o incompatible.
- [x] Mostrar cada regla con estado PASS/FAIL y sus detalles.
- [x] Mostrar el estado de publicación del evento.
- [x] Actualizar Ayuda para explicar CPU socket, RAM y potencia PSU.
- [x] Eliminar el texto heredado que afirma que no existe comprobación automática.

### Criterios de aceptación

- [x] Se puede demostrar al menos una combinación compatible.
- [x] Se puede demostrar al menos una combinación incompatible.
- [x] Una regla fallida muestra la causa recibida del backend.
- [x] Cada comprobación genera `COMPATIBILITY_CHECKED` en S3.

### Resultado

Implementado y validado el 23 de septiembre de 2026:

- se agregó la ruta pública `/compatibilidad` en la aplicación, el menú móvil,
  la navegación principal y el footer;
- los selectores reutilizan el catálogo compartido, limitan cada categoría a 100
  opciones y priorizan productos con la especificación requerida;
- el botón de ejemplo carga CPU, motherboard, RAM, GPU y PSU con datos válidos;
- la pantalla exige al menos un par capaz de activar una regla;
- el hook agrega un `session_id` de demostración y el `user_id` cuando existe
  una sesión autenticada;
- el resultado distingue compatible/incompatible, PASS/FAIL, detalles por regla
  y publicación/no publicación del evento;
- Ayuda documenta las reglas `CPU_SOCKET`, `RAM_TYPE` y `PSU_POWER`;
- API Gateway validó una combinación completa con tres PASS y publicó
  `compatibility_checked_evt_0bff5302.json`;
- API Gateway validó una combinación incompatible con FAIL en `CPU_SOCKET`,
  mostrando socket de CPU vacío frente a AM5, y publicó
  `compatibility_checked_evt_501b5cdd.json`;
- se agregó una prueba del contrato, validación local y endpoint del servicio;
- `npm test`, `npm run lint` y `npm run build` terminaron con código cero.

## Fase 7: crear el dashboard de Analytics

### Ruta

```text
/analitica
```

### Endpoints a integrar

- [x] `/api/analytics/events/count`.
- [x] `/api/analytics/top-products`.
- [x] `/api/analytics/sales/summary`.
- [x] `/api/analytics/sales/by-category`.
- [x] `/api/analytics/products/conversion`.
- [x] `/api/analytics/compatibility/failure-rules`.
- [x] `/api/analytics/compatibility/summary`.
- [x] `/api/analytics/users/registrations`.
- [x] `/api/analytics/funnel`.

### Diseño del dashboard

- [x] Mostrar tarjetas KPI para eventos, ventas y compatibilidad.
- [x] Mostrar una tabla o gráfico compacto de eventos por tipo.
- [x] Mostrar los cinco productos más vistos.
- [x] Mostrar ventas por categoría.
- [x] Mostrar conversión de vistas a ventas.
- [x] Mostrar reglas de compatibilidad fallidas, incluyendo un estado vacío válido.
- [x] Mostrar registros de usuarios por día.
- [x] Mostrar el embudo vistas → compatibilidad → orden.
- [x] Mostrar que el backend consultado es Athena.
- [x] Permitir reintentar cada bloque o recargar el dashboard.
- [x] Tratar independientemente errores parciales para que una consulta fallida no
  oculte todo el dashboard.

No es obligatorio agregar una biblioteca pesada de gráficos. Barras construidas
con CSS, tablas y tarjetas son suficientes si mantienen el diseño existente.

### Criterios de aceptación

- [x] Los nueve endpoints se consultan mediante API Gateway.
- [x] El dashboard muestra los resultados reales usados en la rúbrica.
- [x] Se visualizan `backend: athena`, duración y estado de carga.
- [x] Una respuesta sin filas se presenta como cero o “sin datos”, no como error.

### Resultado

Implementado y validado el 23 de septiembre de 2026:

- se agregó la ruta pública `/analitica` sin control de sesión o roles;
- la navegación principal, el menú móvil y el footer enlazan el dashboard;
- los nueve endpoints tienen servicios tipados y estados de consulta
  independientes;
- cada panel muestra carga, error, reintento, backend, duración e ID de ejecución;
- se agregaron KPIs de eventos, ingresos, compatibilidad y usuarios;
- eventos y productos vistos usan barras CSS; ventas, conversión y registros usan
  tablas responsive; compatibilidad y funnel tienen resúmenes propios;
- las listas vacías, incluida la ausencia de reglas fallidas, se presentan como
  estados válidos;
- no se agregó ninguna dependencia de gráficos;
- API Gateway devolvió `backend: athena` en las nueve consultas;
- la validación real mostró 4,250 eventos, 20,004 órdenes, ingresos
  `3922239.52`, cuatro checks de compatibilidad con tasa de 50 % y funnel
  20 → 1 → 1;
- las duraciones observadas estuvieron entre 1,286 ms y 3,433 ms, dentro del
  timeout analítico de 60 segundos;
- las pruebas comprueban las nueve rutas REST;
- `npm test`, `npm run lint` y `npm run build` terminaron con código cero.

## Fase 8: completar contenido y recursos visuales

### Tareas

- [x] Reemplazar textos que describen características del backend anterior.
- [x] Alinear hero, navegación y categorías con la demo actual.
- [x] Completar o retirar referencias a banners inexistentes.
- [x] Convertir imágenes grandes a WebP o AVIF cuando sea sencillo.
- [x] Mantener fallbacks para URLs de imagen ficticias.
- [x] Revisar navegación móvil y tamaños de los formularios nuevos.
- [x] Confirmar contraste, foco de teclado y textos alternativos.

### Criterios de aceptación

- [x] No quedan afirmaciones que contradigan el funcionamiento del backend.
- [x] No aparecen imágenes rotas durante el recorrido principal.
- [x] Las nuevas pantallas parecen parte del mismo producto visual.

### Resultado de la fase 8

- se revisaron los textos de sesión, carrito, compatibilidad y Analytics para que
  describan el comportamiento actual de API Gateway y Athena;
- hero, navegación y las cinco categorías del catálogo quedan visibles también
  en tablet y móvil;
- se retiraron referencias a banners y categorías que no existían y se
  conservaron fallbacks de iconos coherentes con el sistema visual;
- las imágenes rasterizadas usadas por la interfaz se sirven como WebP: hero
  (18 KB) y wordmark (28 KB); los banners sin una imagen correcta usan iconos;
- el cargador de recursos dejó de importar de forma ansiosa todas las imágenes
  del directorio y el favicon usa el SVG válido;
- `ProductImage` conserva el fallback para las URLs ficticias del catálogo;
- formularios, Compatibility y Analytics tienen layouts móviles, tablas con
  desplazamiento horizontal y controles con foco visible;
- los iconos decorativos se excluyeron del árbol de accesibilidad y las imágenes
  informativas mantienen texto alternativo;
- `npm test`, `npm run lint` y `npm run build` terminaron con código cero.

## Fase 9: preparar ejecución y despliegue en AWS Amplify

### Tareas

- [x] Crear un stack CloudFormation separado para AWS Amplify Hosting.
- [x] Usar `npm ci` para instalaciones reproducibles en Amplify.
- [x] Generar el frontend con `npm run build`.
- [x] Publicar `frontend/dist` como aplicación web estática.
- [x] Configurar fallback SPA hacia `index.html`.
- [x] Documentar ejecución local y configuración contra AWS.
- [x] Documentar cómo sustituir el endpoint si se recrea el stack.
- [x] Conectar el stack al repositorio público y a la rama configurada.
- [ ] Desplegar el stack con credenciales AWS y token temporal de GitHub.
- [ ] Confirmar que el primer build de Amplify termina en `SUCCEED`.
- [ ] Registrar el enlace público de Amplify entre los entregables.

### Criterios de aceptación

- [x] `npm run build` termina correctamente.
- [ ] Abrir directamente una ruta como `/productos/1` no devuelve 404.
- [x] La aplicación puede configurarse sin editar código fuente.

### Estado de la cobertura REST exigida por la rúbrica

La rúbrica exige que la UI consuma los cinco microservicios y demuestre al menos
dos operaciones REST de cada uno. El inventario actual es:

| Microservicio | Operaciones invocadas por la UI | Estado |
| --- | --- | --- |
| Identity | registro, login y perfil | Cumple |
| Catalog | lista y detalle de producto | Cumple |
| Orders | crear, listar y ver detalle | Cumple |
| Compatibility | comprobar componentes | Falta una segunda operación |
| Analytics | nueve consultas analíticas | Cumple |

Antes de la entrega se debe añadir y mostrar una segunda operación funcional de
Compatibility; el endpoint de documentación no debe contarse como operación de
negocio. También debe incluirse el enlace público del repositorio GitHub junto
con la URL final de Amplify.

## Fase 10: pruebas y recorrido final

### Pruebas automatizadas

- [ ] Actualizar las pruebas de servicios para los contratos nuevos.
- [ ] Agregar pruebas del servicio de compatibilidad.
- [ ] Agregar pruebas de los nueve servicios analíticos.
- [ ] Probar paginación y filtros del catálogo.
- [ ] Probar restauración y cierre de sesión.
- [ ] Probar que un error parcial de Analytics no derriba todo el dashboard.
- [ ] Ejecutar `npm test`, `npm run lint` y `npm run build`.

### Prueba manual contra AWS

- [ ] Abrir la página principal.
- [ ] Buscar y abrir un producto.
- [ ] Registrar un usuario de demostración.
- [ ] Iniciar sesión y recargar la página.
- [ ] Agregar un producto al carrito.
- [ ] Crear una orden y abrir su detalle.
- [ ] Ejecutar una compatibilidad válida.
- [ ] Ejecutar una compatibilidad fallida.
- [ ] Abrir Analytics y comprobar los nueve resultados.
- [ ] Confirmar en S3 los eventos de identidad, catálogo, orden y compatibilidad.
- [ ] Confirmar que el dashboard identifica Athena como backend.

## Recorrido sugerido para la exposición

1. Mostrar la tienda y explicar que todo entra por API Gateway.
2. Registrar un usuario para producir `USER_REGISTERED`.
3. Buscar un producto proveniente de PostgreSQL.
4. Ejecutar una comprobación compatible y otra incompatible.
5. Crear una orden almacenada en MySQL y producir `ORDER_CREATED`.
6. Mostrar la orden en el historial del usuario.
7. Abrir el dashboard analítico.
8. Explicar que las métricas son consultas reales a Athena sobre S3 catalogado
   por Glue.
9. Mostrar brevemente los objetos generados en el data lake.

## Definición de terminado

La actualización del frontend se considera terminada cuando:

- [ ] utiliza API Gateway como único punto de entrada en AWS;
- [ ] permite demostrar Identity, Catalog, Orders y Compatibility;
- [ ] expone en una pantalla los nueve resultados de Analytics;
- [ ] maneja el catálogo masivo sin renderizar 20,000 tarjetas;
- [ ] mantiene la identidad visual actual en escritorio y móvil;
- [ ] no contiene textos heredados que contradigan al backend;
- [ ] las pruebas, lint y build terminan correctamente;
- [ ] existe una guía corta y reproducible para ejecutar la demo.
