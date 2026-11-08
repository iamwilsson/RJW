# Contexto del proyecto RJW

Actualizado: 2026-11-07

## Resumen

RJW es un prototipo autónomo de una plataforma inmobiliaria y de servicios. `index.html` abre directamente en el navegador; `properties-data.js` contiene las fichas iniciales.

## Tecnologías

- HTML5 para la estructura de la página.
- CSS escrito dentro de `index.html`.
- JavaScript vanilla en `index.html` y `properties-data.js` para navegación, renderizado, filtros, contadores, carruseles y formularios.
- Bootstrap 5.3.3 CSS y Bundle JS cargados desde jsDelivr CDN.
- Imágenes JPEG y PNG locales en la carpeta raíz del proyecto.
- `localStorage` del navegador actual para conservar altas, aprobaciones, ediciones y eliminaciones.

## Estructura de datos de propiedades

Las fichas se cargan desde `properties-data.js` al arreglo `properties`; los cambios de demostración se guardan en `localStorage`. El esquema usado es:

- `category`: categoría de inmueble, por ejemplo `Casas`, `Terrenos` o `Apartamentos`.
- `modes`: modalidades disponibles: `sale`, `rent` o ambas. Esta propiedad determina en qué ventanas aparece la ficha y en qué contadores se incluye.
- `name`, `description`, `measures`, `location`, `department`.
- `services`: arreglo de servicios disponibles; se usa también para el filtro.
- `deedType`, `documentStatus`: estado/tipo de escritura.
- `paymentOptions`: arreglo de formas de pago. La modalidad `rent` no debe agregarse como forma de pago.
- `price`, `image`, `imageAlt`: precio e imagen principal.
- `images`, `imageAlts`: arreglos opcionales para fichas con varias fotos; se muestran con el carrusel común.
- Campos opcionales que ya utiliza el proyecto: `availableCount`, `availableUnit`, `extras`, `paymentTerms`, `unitPrice`, `waterSources` y `serviceNotes`.
- Campos del flujo de publicación: `contactEmail`, `publicationStatus`, `verifiedByDeveloper` y `userSubmitted`.
- Campos opcionales para maquinaria, vehículos y equipos: `brand`, `model`, `year`, `condition`, `usageMetric`, `technicalDetails` y `warranty`.

Las fichas iniciales están en `properties-data.js`; las altas, cambios y bajas se guardan en el navegador actual. Para evitar falsos positivos en filtros, `services` solo debe incluir servicios realmente disponibles; notas como “Sin agua ni luz” se guardan en `serviceNotes`.

## Estado construido

- Navegación de Inicio, Venta, Renta, Servicios y Asesoría Jurídica.
- Menús de categorías para Venta y Renta con Terrenos, Apartamentos, Casas, Vehículos, Maquinaria y Habitaciones.
- Categoría Equipos disponible en Venta, Renta y el formulario de publicación.
- Pantalla compartida de resultados por categoría y modalidad, con estado vacío y acceso a los detalles de cada ficha.
- Pantalla de detalle con carrusel de imágenes, datos de la propiedad e iconos locales para medidas, ubicación, servicios, escritura, pagos y precio.
- Formulario de publicación con categoría, una o ambas modalidades, datos inmobiliarios o técnicos, precio total/unitario, disponibilidad, contacto e imágenes múltiples.
- Publicaciones comunes guardadas como pendientes en SQLite; no aparecen en resultados hasta aprobarse.
- Login de desarrollador mediante `RJW_DEVELOPER_KEY`, validado en servidor; sesión con cookie `HttpOnly`, `SameSite=Strict`, token CSRF y límite de intentos.
- El desarrollador autenticado puede aprobar, editar y eliminar publicaciones; las nuevas publicaciones del administrador se publican de inmediato y llevan insignia verificada.
- Vehículos, Maquinaria y Equipos muestran campos técnicos específicos en el formulario de publicación.
- Formulario de contacto en cada detalle con nombre, teléfono, correo y mensaje; confirma una simulación local, sin enviar correo real.
- Filtros combinables por los 22 departamentos de Guatemala, Agua/Luz/Drenaje, tipo de escritura y forma de pago; botón para limpiar los filtros.
- Contadores de propiedades activas, ventas y rentas calculados desde `properties` y `modes`.
- Catálogo de servicios mostrado desde un arreglo JavaScript.
- Bootstrap cargado desde CDN con su hash de integridad corregido.

## Fichas registradas

Hay 10 fichas: 3 Casas, 6 Terrenos y 1 Apartamento.

- Casa en Ciudad de Guatemala: Venta y Renta.
- Casa en Poptún, Petén: Venta.
- Casa en Chahal, Alta Verapaz: Venta.
- Predio comercial en Tierra Colorada, Livingston, Izabal: Venta.
- Parcela de 29 manzanas en Cobán, Alta Verapaz: Venta.
- Seis lotes en Gaspar, Alta Verapaz: Venta.
- Lote en Carchá, Alta Verapaz: Venta.
- Lote en Santa Lucía Cotzumalguapa, Escuintla: Venta.
- Manzana en Aldea Siguanja 1, Chahal, Alta Verapaz: Venta.
- Apartamento en Barrio el Centro, Fray, Alta Verapaz: Renta; cinco habitaciones disponibles.

Los contadores actuales son 10 propiedades activas, 9 ventas y 2 rentas. Una ficha puede contar en ambos modos.

La base de datos es local a esta máquina por defecto. El servidor escucha en `127.0.0.1:8000`; no está expuesto a la red local salvo que se cambie `RJW_HOST`.

## Pendiente

- Para producción, desplegar detrás de HTTPS y un servidor WSGI/ASGI de producción; `http.server` solo es para desarrollo local.
- Para varios usuarios/equipos, mover SQLite a un servicio de base de datos compartido y configurar respaldo.
- Añadir usuarios individuales, roles y auditoría; actualmente solo existe una clave compartida de desarrollador.
- Incorporar controles de autorización de campos y validaciones de negocio más específicos por categoría.
- Conectar el formulario de contacto a un backend y a un proveedor de correo; hoy solo muestra una confirmación visual ficticia.
- Implementar mapa para las ubicaciones.
- Conectar las acciones de contacto/consulta; el botón “Consultar” todavía no tiene flujo funcional.
- Completar la sección de Asesoría Jurídica, que actualmente es informativa/placeholder.
- Completar los datos que aún faltan en algunas fichas, como precios o características no proporcionadas.
- Añadir pruebas automatizadas de navegador para login, categorías, formularios y operaciones CRUD además de las pruebas API.

## Inicio local

Desde PowerShell, en la carpeta del proyecto, ejecutar `./run-rjw.ps1`. El script solicita la clave de desarrollador con entrada segura, la pasa al proceso servidor sin escribirla en `index.html` y la quita del entorno al detenerlo. Abrir `http://127.0.0.1:8000`.

También puede iniciarse manualmente con `RJW_DEVELOPER_KEY` definido en el entorno y `python server.py`. No abrir `index.html` directamente con `file://`: la carga de datos y la autenticación requieren la API.

El login protege operaciones del servidor; no existe autenticación de usuarios comunes. El formulario de contacto continúa siendo una simulación y no envía correo real. El servidor de la biblioteca estándar es para desarrollo local, no para exposición directa a Internet.

## Convenciones para próximas fichas

- Registrar cada inmueble en `properties` y usar `modes` para indicar exactamente si es Venta, Renta o ambas.
- Para vehículos, maquinaria o equipos, completar datos técnicos en lugar de campos de escritura/servicios inmobiliarios.
- Mantener ubicación, servicios, escritura y formas de pago en campos estructurados para que los filtros funcionen.
- No inventar información que no haya sido proporcionada.
- Copiar las imágenes a la carpeta del proyecto y referenciarlas con rutas relativas. Usar `images`/`imageAlts` cuando haya más de una foto; el carrusel existente se encarga de mostrarlas.
- Al agregar una ficha, los contadores se actualizan automáticamente desde el arreglo al cargar la página.
