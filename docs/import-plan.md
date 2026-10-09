# Plan de importación de música y generación de catálogo

Estado: implementación funcional completada y comprobada localmente el 9 de octubre
de 2026. La validación de esta entrega en CI y la revisión visual en Windows/macOS
quedan pendientes; véanse los resultados medidos en [VALIDATION.md](../VALIDATION.md).

## Resultado esperado

La acción **Importar música…** permite seleccionar una carpeta y construir un catálogo
con sus archivos FLAC/MP3, incluidas las subcarpetas. También permite añadir o actualizar
la música de esa carpeta en el catálogo abierto. Al terminar, la GUI muestra los datos
guardados, sin necesidad de ejecutar scripts ni utilizar SQLiteBrowser.

El núcleo coordina la exploración, lectura de metadatos y persistencia mediante contratos
Python independientes de Qt. La GUI recoge la solicitud, presenta el progreso y muestra
el resultado. Los archivos musicales se leen sin modificarlos.

## Punto de partida comprobado

| Componente existente | Qué se reutiliza o amplía |
| --- | --- |
| [`ImportAudio`](../src/trackfolio/application/catalog.py) | Importación individual y validación de pertenencia a una raíz. Falta la coordinación de una carpeta. |
| [`read_metadata`](../src/trackfolio/infrastructure/metadata.py) | Lectura FLAC/MP3 por contenido, etiquetas originales, datos ausentes y portada incrustada o `album.jpg`. |
| [`SqliteCatalogRepository`](../src/trackfolio/infrastructure/catalog.py) | Transacción por archivo y actualización por biblioteca/ruta, conservando identificadores. |
| [`migrate_database`](../src/trackfolio/infrastructure/database.py) | Creación del esquema canónico mediante Alembic y rechazo de bases ajenas. |
| [`open_catalog`](../src/trackfolio/infrastructure/session.py) | Apertura exclusivamente de lectura para consultar el resultado. |
| [`CatalogController`](../src/trackfolio/interfaces/gui/controller.py) | Trabajos asíncronos, descarte de respuestas antiguas y conservación de la selección. |
| [`scripts/import_audio.py`](../scripts/import_audio.py) | Herramienta individual que debe conservar sus argumentos y usar las reglas compartidas. |

La escritura actual vuelve a consultar el detalle completo después del commit. El lote
necesita un resultado ligero para evitar recargar portadas y para distinguir una escritura
confirmada de un error posterior de lectura. El cierre actual usa `waitForDone()` en el
hilo gráfico: habrá que adaptar ese ciclo de vida para una importación larga.

## 1. Alcance y reglas de la primera entrega

- Una carpeta raíz por operación, recorrida de forma recursiva. Se seleccionan archivos
  regulares con extensión `.flac` o `.mp3`, sin distinguir mayúsculas. El lector comprueba
  el contenido real; un archivo corrupto con esa extensión produce una incidencia.
  Los archivos con otras extensiones se ignoran, aunque contengan audio reconocible.
- La raíz se normaliza y valida antes de preparar el destino. Las rutas del catálogo
  siguen siendo relativas a esa raíz, con el mismo criterio que la importación actual.
- No seguir enlaces simbólicos de archivos o directorios ni puntos de unión que puedan
  introducir otra raíz o ciclos. Comprobar también la pertenencia a la raíz al importar,
  por si el árbol cambia desde la exploración.
- Orden determinista por ruta relativa. Se enumeran rutas antes de importar; se conserva
  en memoria la lista de candidatos, sin cargar sus metadatos o imágenes por adelantado.
- **Crear catálogo** usa un destino nuevo, con `.tfo` como extensión sugerida. Si la ruta
  ya existe, se rechaza; la creación debe reservarla de forma exclusiva para evitar
  sobrescrituras incluso si aparece después de validar el formulario.
- **Usar catálogo abierto** añade archivos nuevos y actualiza los ya importados. Debe
  validar que sigue siendo un catálogo Trackfolio compatible y escribible. Se conserva
  la extensión de cualquier catálogo existente admitido por el visor.
- Cada candidato se relee en cada importación. La misma raíz y ruta relativa conservan
  `file_id` y `track_id`; los metadatos eliminados del archivo también se eliminan de su
  registro. El contador de actualizados incluye los archivos releídos sin cambios.
- Otra raíz, una copia o un renombrado se consideran ubicaciones nuevas. No se fusionan
  grabaciones por título, etiquetas, formato o contenido. Seleccionar una subcarpeta como
  raíz diferente tampoco equivale a reimportar la raíz original.
- No borrar registros de archivos desaparecidos ni limpiar entidades sin referencias.
  Se mantienen las reglas actuales de álbumes, artistas, géneros y carátulas, los campos
  ausentes como `NULL`/tuplas vacías y su presentación en blanco.
- Una importación secuencial y un escritor por ventana. La selección de archivos sueltos
  en la GUI, varias raíces simultáneas, vigilancia de carpetas, huellas para omitir archivos
  sin cambios, edición de etiquetas y detección de duplicados quedan para otras entregas.

Este alcance utiliza el esquema actual. No requiere modificar `001_initial`, el SQL
exportado ni `migrations/env.py`. Cualquier necesidad futura de columnas o historial se
resolverá mediante una nueva revisión de Alembic.

La entrega posterior de [artistas únicos por nombre](artist-identity-plan.md) está
implementada: sustituye la reutilización contextual de artistas y añade la revisión `002`
para consolidar catálogos existentes. Los párrafos anteriores describen el alcance original
de esta importación.

## 2. Caso de uso y contratos del núcleo

Crear `application/import_catalog.py` con el caso de uso `ImportCatalog`. Recibe una
solicitud y adaptadores inyectados; devuelve un informe y publica progreso mediante un
callback Python. La cancelación se consulta mediante un contrato Python, sin señales Qt.
Los DTO serán dataclasses inmutables. Los errores de lectura y destino se definen en
aplicación; los adaptadores traducen sus excepciones técnicas a esos errores, manteniendo
la compatibilidad de los puntos de entrada existentes.

| Contrato propuesto | Contenido o responsabilidad |
| --- | --- |
| `ImportRequest` | Raíz musical, ruta de destino y modo `create`/`update`. |
| `AudioSource` | Ruta del candidato y ruta relativa a la raíz validada. |
| `AudioScanner` | Enumeración cancelable de candidatos e incidencias de exploración. Implementación en infraestructura. |
| `MetadataReader` | Contrato existente de lectura de un archivo, con errores traducidos a errores de aplicación. |
| `CatalogImportTargetFactory` | Prevalidación sin escritura y apertura/cierre del destino escribible cuando sea necesario. |
| `CatalogWriter` | Guardar los metadatos de un archivo y devolver un `SaveOutcome`. |
| `SaveOutcome` | `file_id`, `track_id` y operación `created`/`updated`, confirmados por la transacción. |
| `ImportProgress` | Fase, candidatos encontrados, total conocido o `None`, procesados, creados, actualizados, fallidos y ruta actual. |
| `ImportIssue` | Ruta, etapa (`scan`, `read`, `write`, `cleanup`) y causa presentable; sin excepciones de Mutagen/SQLAlchemy en el contrato. |
| `ImportReport` | Destino, estado `completed`/`cancelled`/`failed`, contadores finales, incidencias y causa fatal cuando exista. |

El informe distingue incidencias de exploración de archivos fallidos: una carpeta
inaccesible no es un archivo de audio procesado. Al terminar la exploración,
`procesados = creados + actualizados + fallidos`; lo pendiente es el total de candidatos
menos los procesados. Los archivos ignorados por extensión o enlaces no aumentan los
fallidos. Un estado `completed` puede contener incidencias y debe presentarse como tal.
Si falla la escritura de un candidato, cuenta como fallido y procesado; si falla la
preparación global del destino, los candidatos sin guardar siguen pendientes. Si se
cancela la exploración, el informe indica que el total definitivo es desconocido.

La operación sigue esta secuencia:

1. Validar raíz y destino sin crear ni migrar una base de datos.
2. Explorar con progreso indeterminado y comprobaciones de cancelación. Una raíz
   inaccesible impide iniciar; un subdirectorio inaccesible se registra y permite seguir.
3. Publicar el total de candidatos y leerlos uno a uno mediante el lector actual.
4. Abrir el escritor al obtener los primeros metadatos válidos, comprobar de nuevo la
   cancelación y guardar cada archivo en su propia transacción.
5. Contabilizar únicamente commits confirmados. Emitir progreso sin devolver metadatos,
   BLOBs o el detalle completo de cada canción a la GUI.
6. Cerrar el escritor en todas las salidas y devolver el informe, incluido el avance
   parcial si se cancela o falla la operación.

Separar la preparación/escritura común de un archivo para compartirla con `ImportAudio`.
Mantener el resultado público individual `CatalogEntry` y las consultas existentes;
el lote utilizará la escritura ligera. No consultar la lista completa para decidir si un
archivo es nuevo: esa decisión se toma en la misma transacción que lo guarda.

## 3. Fallos, cancelación y persistencia

| Situación | Comportamiento previsto |
| --- | --- |
| Carpeta vacía o sin candidatos | Mostrar que no se encontró FLAC/MP3. No crear un catálogo ni cambiar el visible. |
| Archivo corrupto, ilegible o desaparecido | Registrar la incidencia y continuar con el siguiente. |
| Subdirectorio inaccesible | Seguir con el resto y mostrar que la exploración fue incompleta. |
| Destino ajeno, incompatible o sin permisos | Terminar con error de aplicación sin adoptar ni sobrescribir el archivo. |
| Error de almacenamiento, esquema o bloqueo SQLite | Espera acotada; terminar con causa fatal y avance confirmado. Sin reintentos indefinidos. |
| Cancelación durante exploración | Detener la enumeración; no comenzar a importar el listado parcial. |
| Cancelación durante importación | Comprobar antes de leer y antes de guardar; dejar terminar la transacción activa y detenerse antes del siguiente archivo. |
| Cancelación o fallo tras guardar archivos | Conservar las transacciones completadas y mostrar que el resultado es parcial. |

La creación del catálogo nuevo se difiere hasta disponer de metadatos válidos. Si no
se confirma ninguna escritura, cerrar los recursos e intentar eliminar únicamente el
archivo nuevo creado por esa operación. Si esa limpieza falla, registrar la incidencia
y la ruta restante en el informe. Un catálogo existente nunca se elimina. Si ya hubo
commits, el catálogo nuevo permanece disponible aunque el resultado sea parcial.

La cancelación es cooperativa: no interrumpe por fuerza Mutagen, una operación del
sistema de archivos o una transacción. La GUI muestra **Cancelando…** hasta que el
trabajador alcanza un punto de parada y libera los recursos. No prometer cancelación
instantánea si el archivo o el dispositivo tarda en responder.

## 4. Flujo de la GUI

Añadir un botón y acción **Importar música…**, con icono SVG propio, junto a **Abrir
catálogo…** y **Actualizar**. Debe estar disponible sin catálogo; el estado inicial
indicará que se puede abrir uno o crearlo importando música.

El diálogo contiene:

- **Carpeta de música**, con selector Qt y aviso de que incluye subcarpetas FLAC/MP3.
- **Destino**: usar el catálogo abierto, seleccionado inicialmente cuando lo haya,
  o crear uno nuevo. Sin catálogo abierto sólo está disponible la creación.
- **Archivo de catálogo**, para el modo de creación, con nombre `.tfo` sugerido y
  ubicación elegida por el usuario. El directorio inicial procede de las preferencias
  existentes o del directorio de datos de usuario de Trackfolio, sin rutas del checkout.
- **Importar** y **Cancelar**. Cancelar el formulario no crea archivos ni inicia trabajos.

Al usar el catálogo abierto, explicar: «Se añadirán canciones nuevas y se actualizarán
las ya importadas desde esta carpeta». Durante el trabajo, indicar que cancelar conserva
lo que ya se haya guardado.

El progreso muestra la exploración indeterminada y después una barra con
`procesados/total`, archivo actual y contadores. **Cancelar** permanece accesible.
El resultado reúne creados, actualizados, fallidos y pendientes, con una lista consultable
de incidencias. No abrir un diálogo por cada archivo fallido ni presentar excepciones
técnicas crudas al usuario.

Cuando exista un resultado nuevo con archivos guardados, abrirlo automáticamente mediante
el lector actual y recordar la ruta sólo si se abre correctamente. Si el destino era el
catálogo abierto, recargar lista y detalle conservando la selección por `file_id`.
Aplicar este comportamiento también a resultados parciales; si no hubo escrituras,
mantener o restaurar el catálogo anterior. Un error al abrir el resultado debe indicar
que los archivos ya se guardaron y permitir volver a abrirlo.

## 5. Trabajo asíncrono y ciclo de vida

Conectar los adaptadores desde `startup.py`. El controlador recibe el caso de uso o
ejecutor de importación mediante un contrato; no importa SQLAlchemy, Alembic ni Mutagen.
El motor escribible se crea, utiliza y libera dentro del trabajo de importación. La
sesión `CatalogSession` continúa siendo exclusivamente de lectura.

Estados previstos: disponible → preparando → explorando → importando → finalizando
→ resultado; la solicitud de cancelación añade el estado cancelando. Separarlos del
indicador actual de consulta para que un detalle antiguo no reactive acciones.

- Deshabilitar Importar, Abrir, Actualizar y nuevas selecciones mientras exista una
  operación de importación. Mantener visibles la lista y el detalle ya cargados.
- Invalidar respuestas de consultas anteriores y esperar su finalización mediante
  eventos, sin bloquear el hilo gráfico. Retirar/cerrar la sesión de lectura cuando
  termine su último trabajo, antes de iniciar el escritor.
- Traducir callbacks de progreso y resultado a señales encoladas identificadas por
  operación. Los widgets se actualizan exclusivamente en el hilo gráfico.
- Limitar la frecuencia de progreso para no saturar la cola de eventos con una biblioteca
  grande; el informe final siempre contiene los contadores exactos.
- Al terminar, liberar primero el escritor y después abrir/restaurar el lector. Conservar
  ruta y selección anteriores durante este proceso.
- Al cerrar la ventana durante una importación, solicitar cancelación y diferir el cierre
  real. Mantener vivos ventana, controlador y señales hasta liberar los trabajadores.
  Adaptar `closeEvent`, `shutdown`, los auxiliares de disposición y `interfaces/gui/app.py`:
  sus rutas `aboutToQuit` y `finally` también deben respetar ese orden. Canalizar las
  salidas normales por el cierre diferido y prever la liberación final antes de disponer
  objetos Qt si el bucle de eventos ya terminó. No usar el actual `waitForDone()` para
  esperar una importación larga mientras la ventana debe seguir procesando eventos.

## 6. Fases de implementación y comprobación

| Fase | Trabajo | Criterio para avanzar |
| --- | --- | --- |
| 1. Contratos y reglas | Solicitud, progreso, informe, incidencias, cancelación y puertos en `application/import_catalog.py`; validación compartida con importación individual. | Pruebas del caso de uso con adaptadores de prueba, ejecutables sin Qt ni SQLite. |
| 2. Adaptadores | Explorador en `infrastructure/audio_scan.py`, destino escribible en `infrastructure/import_target.py` y escritura ligera en `infrastructure/catalog.py`. | Recorrido controlado, conteos de creación/actualización, commits/rollback y cierre verificados con directorios y SQLite temporales. |
| 3. Orquestación completa | Conectar `ImportCatalog`, errores de lectura/persistencia y composición reutilizable; conservar compatibilidad de `scripts/import_audio.py`. | Importar y reimportar una carpeta temporal real FLAC/MP3 produce el catálogo esperado y un informe exacto. |
| 4. Presentación | Botón/acción, diálogo en `interfaces/gui/import_dialog.py`, progreso/resumen, icono, estilos y manifiesto de recursos. | QtTest cubre selección de origen/destino, estados, diálogos cancelados y presentación de resultados. |
| 5. Integración asíncrona | Worker/controlador de importación, composición en `startup.py`, pausa de consultas, recarga y cierre diferido. | GUI receptiva, una sola importación, cancelación parcial y cierre sin conexiones ni trabajadores abandonados. |
| 6. Entrega | Documentación de uso, comprobaciones del proyecto, paquete instalado y matriz multiplataforma. | Resultados registrados; pruebas automáticas y revisión visual manual identificadas por separado. |

Las fases 1–3 deben completarse antes de conectar escrituras a la GUI. La presentación
de la fase 4 puede desarrollarse en paralelo a los adaptadores una vez fijados los contratos.

### Casos que deben quedar verificados

- Árbol recursivo con FLAC/MP3, extensiones en mayúsculas, Unicode y espacios; archivos
  ajenos, enlaces/puntos de unión, carpetas vacías e incidencias de permisos.
- Reimportación sin duplicar rutas y conservando identificadores; desaparición de etiquetas
  y actualización de relaciones; archivos ausentes que no provocan borrados del catálogo.
- Metadatos completos, parciales y vacíos, portadas incrustadas y `album.jpg`, etiquetas
  originales y orden de créditos. Reutilizar las comprobaciones individuales existentes.
- Archivo inválido seguido de uno válido; fallo fatal tras commits anteriores; rollback
  del archivo en curso; resultado ligero sin lectura posterior de BLOBs.
- Destino desconocido o ya existente en modo creación, raíz inválida y ningún archivo
  importable: no alterar archivos previos; comprobar la ausencia de catálogo nuevo vacío
  cuando no se creó o su limpieza tuvo éxito, y el informe si falla esa limpieza.
- Cancelación antes de empezar, durante exploración, después de leer y tras un commit;
  conteos monotónicos y exactos; recursos cerrados en éxito, error y cancelación.
- GUI → caso de uso → lector Mutagen → SQLite con audio controlado temporal. Consultar
  luego metadatos y portada aunque se retire la música original.
- Selección conservada al actualizar, informes parciales visibles y errores recuperables;
  consultas antiguas que no sustituyen resultados ni reactivan acciones de importación.
- Trabajo largo controlado con eventos de sincronización: la ventana procesa eventos,
  cancelar funciona y cerrar espera de forma asíncrona. Evitar pruebas basadas en sleeps.
- Salida de `QApplication`, además de cierre de ventana: cancelar, liberar el escritor
  y disponer los objetos Qt en ese orden, incluido el camino de limpieza de `app.py`.
- Sesión de consulta que sigue rechazando escrituras y núcleo que sigue funcionando
  sin instalar PySide6.

Añadir pruebas en `tests/test_import_catalog.py`, `tests/test_audio_scan.py` y
`tests/test_import_target.py`; ampliar las pruebas actuales de catálogo, widgets,
integración GUI y cierre. Utilizar sólo carpetas, audio y bases de datos temporales.

### Validación de la entrega

Ejecutar Ruff, formato, mypy y pytest con `uv run --locked`, usando el extra `gui` para
las comprobaciones gráficas. Mantener las pruebas del núcleo sin Qt y ampliar la matriz
existente de Windows x86-64, GNU/Linux x86-64 y macOS Intel/Apple Silicon. No se prevén
dependencias nuevas; conservar el lock y la preparación portable.

Comprobar el wheel instalado fuera del checkout: debe poder generar y abrir un catálogo
usando las migraciones y los recursos empaquetados. Revisar manualmente selección de
carpetas, destino, progreso, cancelación y cierre con una biblioteca real elegida para
la validación. Registrar SO, arquitectura y backend; `offscreen` no acredita interacción
ni apariencia en un escritorio real. La revisión visual de Windows/macOS sigue pendiente
en la fase anterior y debe mantenerse explícita hasta realizarla.

Actualizar README, `docs/database.md`, `docs/architecture.md`, `docs/gui-plan.md` y
`VALIDATION.md` al implementar. Corregir también las menciones antiguas de `database.md`
que aún describen la GUI como pendiente. Marcar este plan como implementado únicamente
cuando el flujo completo y sus comprobaciones hayan terminado.
