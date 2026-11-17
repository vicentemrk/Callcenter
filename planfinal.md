# Plan final: reestructuración Marvel de CallCenterGamer

## 1. Objetivo del proyecto

Transformar el proyecto CallCenterGamer en una plataforma temática de Marvel que
combine:

1. Un catálogo de películas, series y personajes Marvel.
2. Un sistema de atención al cliente orientado a consultas sobre ese catálogo,
   merchandising, cómics, juguetes, juegos y eventos.
3. Una experiencia visual coherente con una identidad Marvel basada en negro y
   rojo intenso.
4. Reseñas temáticas de usuarios.
5. Dos páginas de aterrizaje: una institucional del call center y otra
   específica del universo Marvel.
6. Una integración verificable entre las fichas del catálogo y los tickets.

Este documento es únicamente el plan. No se deben comenzar las implementaciones
hasta aprobar el alcance, las decisiones abiertas y el orden de las fases.

---

## 2. Resumen de `cambios_marvel.txt`

### 2.1. Aplicación Marvel y catálogo

- Se creó la app Django `marvel`.
- Se creó `ElementoCatalogo`, un modelo único para películas, series y
  personajes.
- La unicidad se garantiza por `(tipo, mcu_id)`, porque la API reutiliza IDs
  entre tipos de recurso.
- Se agregó el cliente HTTP `marvel/mcu_client.py` con:
  - endpoints de películas, series y personajes;
  - búsquedas y detalles;
  - `/health`;
  - timeout, reintentos limitados y excepciones propias;
  - validación de respuestas y traducción de errores HTTP.
- Se implementó `marvel/services.py` para mapear y guardar datos de forma
  idempotente.
- Se implementó el comando `sincronizar_mcu` con paginación, límites por tipo,
  estadísticas y manejo de errores.

### 2.2. Catálogo visual

- Se agregaron rutas públicas `/marvel/` y `/marvel/<id>/`.
- El listado tiene búsqueda por nombre, filtros por tipo y fase, y paginación.
- El detalle muestra información de cada elemento, imagen o placeholder y datos
  adicionales conservados desde la API.
- Las vistas leen la base local y no consultan la API durante la navegación.
- El catálogo se enlazó desde el header compartido.

### 2.3. Integración con el sistema de tickets

- `Preguntas.elemento_catalogo` relaciona opcionalmente un ticket con una ficha
  Marvel mediante `ForeignKey` y `SET_NULL`.
- Al crear una pregunta se puede seleccionar un elemento Marvel activo.
- La ficha Marvel permite iniciar una consulta con el elemento preseleccionado.
- Los tickets muestran el elemento relacionado en:
  - la conversación;
  - el historial del cliente;
  - el panel administrativo.
- Se agregó auditoría cuando cambia la relación del ticket con el elemento.
- Se respetaron las restricciones existentes de autenticación y roles.

### 2.4. Estado técnico verificado

- Catálogo sincronizado: 75 películas, 56 series y 375 personajes, 506
  elementos en total.
- No hay duplicados por `(tipo, mcu_id)`.
- Migraciones aplicadas hasta `online.0009` y `marvel.0001`.
- La suite registrada en la bitácora llegó a 116 pruebas exitosas.
- `manage.py check` y `makemigrations --check --dry-run` fueron verificados
  correctamente.
- La sincronización no implementa desactivación automática de elementos
  ausentes de la API; queda fuera del alcance actual salvo nueva autorización.

### 2.5. Situación visual actual

El proyecto todavía conserva gran parte de la identidad original gamer:

- `index.html` presenta “Call of Gamers”.
- Las categorías de preguntas siguen siendo hardware, software, conexión,
  cuenta, pago, rendimiento y otros.
- El texto del asistente IA todavía menciona problemas técnicos de hardware,
  software y conexión.
- El footer existente usa `position: fixed`, por lo que debe corregirse para
  quedar al final del documento.
- El catálogo Marvel tiene estilos propios y modo oscuro, pero utiliza la
  paleta anterior y no constituye todavía el rebranding completo del proyecto.

---

## 3. Requisitos del archivo `cosasquehacer.txt`

| Requisito                                                                      | Estado actual                          | Trabajo necesario                                                                                |
| ------------------------------------------------------------------------------ | -------------------------------------- | ------------------------------------------------------------------------------------------------ |
| Tema visual total Marvel, negro y rojo intenso                                 | Parcial                                | Definir tokens visuales y aplicarlos a header, landing, call center, administración y catálogo |
| Preguntas sobre merchandising, películas, cómics, juguetes, juegos y eventos | Pendiente                              | Reemplazar categorías, textos, clasificación IA, formularios, filtros y datos de prueba        |
| Sistema de reseñas con referencias temáticas                                 | Pendiente                              | Diseñar modelo, permisos, flujo de publicación, UI, moderación y pruebas                      |
| Footer al fondo de la página                                                  | Pendiente                              | Cambiar layout global a flex column y retirar el footer fijo                                     |
| Landing del call center                                                        | Parcial/original                       | Rediseñar la página institucional con CTA y contenido Marvel                                   |
| Landing de Marvel                                                              | Pendiente                              | Crear ruta, vista y plantilla específica del universo Marvel                                    |
| Plataforma de películas personalizada                                         | Parcial/completada en catálogo Marvel | Ajustar identidad, contenido, experiencia de búsqueda y reseñas                                |
| Sistema de call center contextualizado                                         | Parcial                                | Adaptar preguntas, respuestas automáticas, perfiles y textos al dominio Marvel                  |
| Historial de interacciones ligado al catálogo                                 | Completado técnicamente               | Validar UX final, navegación y datos históricos en el rebranding                               |
| Integración catálogo-call center                                             | Completada técnicamente               | Mantenerla durante los cambios y ampliar pruebas de regresión                                   |
| Informe de modificaciones                                                      | Pendiente                              | Crear un informe final después de cerrar la implementación                                     |

---

## 4. Alcance y decisiones que deben aprobarse antes de programar

### 4.1. Identidad de marca

Definir antes de editar CSS:

- rojo principal, rojo hover y rojo oscuro;
- negros y grises de superficies;
- tipografía y jerarquía de títulos;
- iconografía permitida;
- tratamiento de imágenes externas de la API;
- reglas para modo claro y oscuro;
- textos oficiales de marca: “CallCenterGamer”, “Marvel” y nombre de las
  páginas.

La regla base propuesta es usar rojo como acento y acciones, negro como
superficie dominante, texto claro sobre fondos oscuros y suficiente contraste
en formularios, enlaces y foco de teclado.

### 4.2. Modelo de reseñas

Antes de crear migraciones, decidir:

- si una reseña pertenece a una película/serie/personaje o solo a películas;
- si se permite una reseña por usuario y elemento;
- escala de puntuación, por ejemplo 1 a 5;
- si la reseña se publica inmediatamente o queda pendiente de moderación;
- si los administradores pueden ocultar, editar o eliminar;
- si se permite actualizar una reseña;
- longitud mínima y máxima;
- qué “referencia temática” se exige: cita, personaje favorito, saga,
  escena, merchandising relacionado u otro campo estructurado.

Propuesta inicial: reseña de un `ElementoCatalogo`, con puntuación de 1 a 5,
texto, referencia temática opcional, autor, fecha, estado visible y restricción
única por usuario-elemento. La moderación debe ser explícita y no depender de
la IA.

### 4.3. Categorías de preguntas

Propuesta de categorías nuevas:

- Merchandising
- Películas
- Series
- Cómics
- Figuras y juguetes
- Videojuegos
- Eventos
- Cuenta y acceso
- Compras y pagos
- Otros

Debe decidirse si “Series” se mantiene separada de “Películas” o si ambas se
agrupan bajo “Contenido audiovisual”. También debe conservarse una estrategia
de compatibilidad para tickets históricos que aún tengan categorías antiguas.

### 4.4. Contenido de las landing pages

Definir:

- nombre final de la landing principal;
- público objetivo;
- CTA principal;
- contenido de contacto;
- imágenes autorizadas y su procedencia;
- enlaces reales de redes sociales;
- diferencia exacta entre la landing institucional y la landing Marvel.

No se deben incorporar imágenes o textos de terceros sin verificar su licencia.

---

## 5. Plan de ejecución por fases

## Fase 0: preparación y línea base

**Objetivo:** congelar el punto de partida y evitar regresiones.

### Tareas

1. Revisar el estado de Git y separar cualquier cambio ajeno al proyecto.
2. Crear un backup de `db.sqlite3` antes de migraciones.
3. Ejecutar y registrar:
   - `python manage.py check`;
   - `python manage.py makemigrations --check --dry-run`;
   - `python manage.py test --parallel 1`.
4. Tomar inventario de rutas, templates, CSS compartido, roles y permisos.
5. Confirmar que el catálogo contiene los 506 elementos esperados.
6. Documentar la decisión final de marca, categorías y reseñas.

### Criterio de salida

La línea base queda registrada y la suite existente pasa sin cambios funcionales.

---

## Fase 1: arquitectura visual Marvel global

**Objetivo:** establecer una identidad visual única sin romper las funciones
existentes.

### Tareas

1. Identificar estilos globales en:
   - header;
   - tema claro/oscuro;
   - landing actual;
   - inicio del cliente;
   - respuestas;
   - administración;
   - catálogo.
2. Crear o consolidar variables CSS para:
   - fondos;
   - superficies;
   - texto;
   - rojo principal;
   - estados;
   - bordes;
   - foco;
   - espaciado y radios.
3. Reemplazar gradualmente referencias a la paleta gamer anterior.
4. Mantener el modo oscuro y asegurar contraste en ambos temas.
5. Actualizar labels, títulos, botones e iconos que todavía sean gamer o
   técnicos cuando corresponda.
6. Validar responsive, navegación por teclado y estados de foco.

### Criterios de aceptación

- Las páginas principales usan la misma identidad negro/rojo.
- No quedan componentes con la paleta anterior por accidente.
- Claro y oscuro son legibles.
- La suite de regresión continúa pasando.

---

## Fase 2: reestructuración del dominio de preguntas y call center

**Objetivo:** convertir el contenido del call center al contexto Marvel.

### Tareas

1. Cambiar `CATEGORIAS_PREGUNTA` por las categorías aprobadas.
2. Crear una migración de datos para mapear categorías históricas sin perder
   tickets existentes.
3. Actualizar:
   - `PreguntasForm`;
   - formularios administrativos;
   - filtros del panel;
   - analytics;
   - etiquetas visibles;
   - datos de prueba.
4. Revisar la clasificación IA:
   - prompt del dominio;
   - lista de categorías válidas;
   - comportamiento ante respuesta inválida;
   - texto de fallback sin API.
5. Cambiar el texto del asistente IA de soporte técnico a consultas Marvel.
6. Adaptar respuestas, ejemplos y mensajes de ayuda a películas, cómics,
   merchandising, juegos y eventos.
7. Actualizar perfiles y datos de ejemplo para representar clientes interesados
   en Marvel.
8. Revisar que el vínculo `elemento_catalogo` siga siendo opcional y seguro.

### Criterios de aceptación

- Un usuario puede crear tickets con las nuevas categorías.
- Tickets antiguos siguen siendo visibles y editables.
- La IA devuelve solo categorías permitidas o el fallback `otros`.
- Los roles y permisos no cambian.
- Las consultas relacionadas con el catálogo siguen enlazando a su ficha.

---

## Fase 3: footer y estructura de layout

**Objetivo:** dejar el footer al final del documento, no fijo sobre la pantalla.

### Tareas

1. Cambiar el layout global del `body` a una estructura de columna.
2. Hacer que `main` ocupe el espacio disponible cuando el contenido sea corto.
3. Retirar `position: fixed` del footer y cualquier compensación de altura
   asociada.
4. Revisar páginas largas, formularios, catálogo paginado y administración.
5. Mantener el footer visible al final del contenido y no superpuesto.
6. Actualizar contacto, copyright y enlaces con contenido Marvel aprobado.

### Criterios de aceptación

- En páginas cortas, el footer queda abajo del viewport sin cubrir contenido.
- En páginas largas, aparece después del contenido.
- No hay scroll horizontal ni superposición en móvil.
- Claro y oscuro mantienen buen contraste.

---

## Fase 4: landing principal del Call Center

**Objetivo:** reemplazar la landing gamer original por una página institucional
de atención Marvel.

### Tareas

1. Rediseñar `index.html` con:
   - propuesta de valor;
   - atención de consultas Marvel;
   - categorías soportadas;
   - CTA de iniciar sesión/registrarse;
   - acceso al catálogo;
   - explicación de atención y seguimiento.
2. Incorporar imágenes locales o fuentes con licencia compatible.
3. Añadir estados apropiados para visitante autenticado y no autenticado.
4. Evitar duplicar lógica de navegación que ya resuelve el servidor.
5. Adaptar responsive y accesibilidad.

### Criterios de aceptación

- Un visitante entiende qué ofrece el servicio sin autenticarse.
- Los CTA llevan a rutas existentes.
- La página no muestra “Call of Gamers” ni ejemplos de hardware.
- La página funciona sin JavaScript esencial.

---

## Fase 5: segunda landing específica de Marvel

**Objetivo:** crear una entrada temática al universo Marvel y al catálogo.

### Tareas

1. Definir ruta con namespace propio, por ejemplo `/marvel/landing/`, sin
   colisionar con `/marvel/`.
2. Crear vista y template.
3. Incluir:
   - presentación del universo;
   - acceso a películas, series y personajes;
   - búsqueda o CTA hacia el catálogo;
   - CTA para consultar sobre un título;
   - explicación de la atención temática.
4. Agregar enlace desde la landing principal, header o catálogo según la
   navegación aprobada.
5. Probar visitante, cliente, técnico y administrador.

### Criterios de aceptación

- La landing es navegable públicamente.
- Los enlaces al catálogo y login son válidos.
- No se duplica la lógica de detalle ni se consulta la API en la navegación.
- La landing conserva el modo claro/oscuro y el responsive.

---

## Fase 6: sistema de reseñas temáticas

**Objetivo:** permitir que usuarios registrados reseñen elementos del catálogo.

### Tareas

1. Implementar el modelo aprobado y su migración.
2. Agregar validaciones de puntuación, texto y referencia temática.
3. Definir permisos:
   - solo clientes autenticados pueden crear;
   - cada cliente solo puede modificar sus propias reseñas;
   - técnicos/administradores moderan según decisión aprobada.
4. Agregar servicio o helpers para:
   - crear;
   - actualizar;
   - publicar/ocultar;
   - calcular promedio y cantidad.
5. Integrar reseñas en el detalle Marvel.
6. Mostrar promedio, distribución o resumen sin consultas N+1.
7. Agregar moderación al panel administrativo.
8. Registrar auditoría cuando una reseña sea moderada, si se aprueba.
9. Cubrir duplicados, inactivos, usuarios no autenticados, XSS y longitudes.

### Criterios de aceptación

- Una reseña solo puede referir a un elemento válido.
- El usuario no puede suplantar autor ni estado de moderación.
- Las reseñas ocultas no aparecen públicamente.
- Se respetan las reglas de una reseña por usuario-elemento, si se aprueba esa
  decisión.
- El promedio del detalle es correcto y las páginas no generan N+1 evidente.

---

## Fase 7: integración y experiencia completa

**Objetivo:** verificar el flujo completo desde una ficha Marvel hasta la
atención y su historial.

### Tareas

1. Probar el recorrido:
   - landing Marvel;
   - catálogo;
   - búsqueda;
   - detalle;
   - crear consulta;
   - ticket preseleccionado;
   - respuesta del técnico;
   - historial;
   - enlace de regreso a la ficha.
2. Confirmar que un elemento inactivo no se ofrece para nuevas consultas.
3. Confirmar que un ticket histórico conserva su referencia aunque el elemento
   se desactive.
4. Revisar auditoría, roles y acceso directo a URLs.
5. Revisar filtros y analytics con las nuevas categorías.
6. Verificar rendimiento básico con los 506 elementos sincronizados.

### Criterios de aceptación

- El flujo catálogo-call center funciona de punta a punta.
- Los permisos se mantienen en acceso normal y manipulación de parámetros.
- No se pierde información histórica.
- Todas las vistas importantes responden correctamente con datos reales y con
  base vacía.

---

## Fase 8: documentación, pruebas y entrega

**Objetivo:** cerrar el proyecto con evidencia reproducible.

### Tareas

1. Actualizar `cambios_marvel.txt` con las fases nuevas, sin sobrescribir el
   historial.
2. Crear el informe final solicitado:
   - cambios por aplicación;
   - modelos y migraciones;
   - rutas y vistas;
   - integración;
   - decisiones visuales;
   - pruebas;
   - datos sincronizados;
   - limitaciones.
3. Actualizar documentación de instalación y ejecución si cambian comandos.
4. Ejecutar:
   - `python manage.py check`;
   - `python manage.py makemigrations --check --dry-run`;
   - `python manage.py test --parallel 1`;
   - pruebas manuales de rutas públicas y autenticadas;
   - revisión responsive y accesibilidad.
5. Verificar que no se incorporen secretos, imágenes no autorizadas ni claves
   API.
6. Revisar migraciones pendientes, integridad SQLite y backups.

### Criterio de salida

El sistema cumple cada punto de `cosasquehacer.txt`, existe evidencia de
pruebas y el informe final permite explicar qué se modificó y cómo se integran
ambas aplicaciones.

---

## 6. Dependencias y orden obligatorio

1. Las decisiones de marca, categorías y reseñas deben aprobarse antes de
   cambiar modelos o contenido.
2. La Fase 0 precede cualquier migración.
3. La Fase 1 debe preceder a las landing pages para reutilizar los tokens
   visuales.
4. La Fase 2 debe preceder a la actualización final de prompts, analytics y
   formularios.
5. La Fase 3 puede ejecutarse junto a la Fase 1, pero debe validarse antes de
   cerrar las landings.
6. La Fase 6 requiere aprobar primero el modelo de reseñas; no debe improvisarse
   una estructura de base de datos.
7. La Fase 7 depende de que el catálogo, tickets y reseñas estén implementados.
8. La Fase 8 es posterior a todas las fases funcionales.

---

## 7. Riesgos y controles

| Riesgo                                            | Control                                                                            |
| ------------------------------------------------- | ---------------------------------------------------------------------------------- |
| Romper tickets históricos al cambiar categorías | Migración explícita de datos y compatibilidad temporal                           |
| Perder vínculos con el catálogo                 | Mantener FK nullable, `SET_NULL` y pruebas de desactivación                     |
| Sobrecargar la API MCU                            | Seguir usando sincronización local, límites y reintentos actuales                |
| Consultas lentas en reseñas o catálogo          | `select_related`, `prefetch_related`, agregaciones y pruebas con 506 elementos |
| XSS en reseñas o textos de usuarios              | Usar renderizado escapado de Django y validaciones                                 |
| Cambios visuales ilegibles                        | Contraste, foco visible, revisión en claro/oscuro y móvil                        |
| Imágenes sin licencia                            | Preferir assets locales/autorizados y documentar su procedencia                    |
| Dependencia excesiva de IA                        | Fallback determinista y categorías validadas en servidor                          |
| Footer superpuesto                                | Pruebas con páginas cortas, largas y viewport móvil                              |
| Cambios de roles por parámetros manipulados      | Conservar validaciones de servidor y pruebas de autorización                      |

---

## 8. Resultado esperado

Al finalizar, CallCenterGamer debe presentarse como una plataforma Marvel
coherente, no como un call center gamer con un catálogo agregado. El catálogo
debe ser la fuente de referencia de películas, series y personajes; el call
center debe permitir consultas contextualizadas y conservar su historial; las
reseñas deben enriquecer cada ficha; y las dos landing pages deben dirigir al
visitante hacia el catálogo o la atención según su objetivo.

La implementación debe hacerse fase por fase, validando cada salida antes de
continuar con la siguiente. No se recomienda ejecutar una reescritura masiva:
la integración Marvel ya funciona y debe preservarse mientras se modifica la
presentación y se agregan las funcionalidades pendientes.
