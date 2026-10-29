# Validación de Trackfolio

El registro conserva las comprobaciones de cada fase. La infraestructura inicial se validó el 6 de octubre de 2026; el catálogo y su primera GUI se implementaron el 7 de octubre. La edición de etiquetas queda para un incremento posterior.

## Comprobaciones locales

Máquina: GNU/Linux x86-64, Omarchy, glibc 2.44, sesión Wayland con XWayland disponible. El entorno utiliza uv 0.12.10 y CPython 3.13.15 administrado por uv. El Python del sistema se conserva.

| Comprobación | Resultado |
| --- | --- |
| Instalación desde `uv.lock` con extra `gui` | Correcta |
| Preparación GUI con el comando del README | Correcta; backend Wayland |
| Ventana Qt 6.11.2/Fusion y ciclo de eventos con Wayland | Correcta |
| Ventana Qt 6.11.2/Fusion y ciclo de eventos con X11 (`xcb`) | Correcta |
| Qt sin pantalla (`offscreen`) en una copia limpia | Correcta; no cuenta como prueba de escritorio |
| SQLite 3.53.1 mediante SQLAlchemy: escritura, transacción y lectura Unicode | Correcta |
| Copia limpia sin `.venv`, en una ruta con espacios y caracteres Unicode | Preparación de núcleo y GUI correctas |
| Núcleo en esa copia, sin instalar PySide6 | Correcto; dominio y aplicación importables |
| Preparación repetida | Correcta; lock sin modificaciones |
| Manifiesto modificado con `--locked` | Rechazado con error de lock desactualizado |
| Pruebas de scripts | 23 pruebas correctas |
| Ruff y comprobación de formato | Correctos |
| mypy estricto | Correcto: 9 archivos de código |
| Wheel y distribución de fuentes | Construidos correctamente |
| Wheel instalado sin dependencias en un entorno temporal fuera del código fuente | Paquete y recursos importables |
| Workspace y tareas VS Code | JSON válido, rutas relativas, tareas `process`; extensión Ruff instalada |
| Workflow | Validado con actionlint 1.7.12 y acciones fijadas por SHA |

No fue necesario instalar bibliotecas gráficas del sistema en este PC. Las instrucciones para otros equipos están en [docs/environment.md](docs/environment.md).

Versiones principales resueltas: SQLAlchemy 2.1.3, Alembic 1.20.0, Mutagen 1.48.1, platformdirs 4.12.3 y PySide6/Essentials/Addons/shiboken6 6.11.2. Las versiones completas y sus hashes están en `uv.lock`.

## Matriz automatizada de la infraestructura inicial

El workflow comprueba instalación limpia del núcleo sin Qt, instalación GUI desde el lock, diagnósticos, 23 pruebas, Ruff, mypy, construcción y recursos del wheel. Linux añade X11 bajo Xvfb; Windows y macOS comprueban sus backends nativos además de `offscreen`.

| Runner | Arquitectura | Estado |
| --- | --- | --- |
| Ubuntu 24.04 | x86-64 | Correcto: núcleo, Qt offscreen/X11, pruebas y distribución |
| Windows Server 2022 | x86-64 | Correcto: núcleo, Qt offscreen/nativo, pruebas y distribución |
| macOS 15 Intel | x86-64 | Correcto: núcleo, Qt offscreen/nativo, pruebas y distribución |
| macOS 15 Apple Silicon | ARM64 | Correcto: núcleo, Qt offscreen/nativo, pruebas y distribución |

Los cuatro jobs terminaron correctamente en la [ejecución 37457968238 de GitHub Actions](https://github.com/Evilchuck666/Trackfolio/actions/runs/37457968238), sobre la revisión `d201961976d20f78b07d80e6e30071bf28411b77`. Este registro posterior sólo actualiza documentación.

Los runners no cubren todas las versiones mínimas anunciadas ni todos los escritorios. El registro de la GUI del producto figura más abajo.

## Catálogo inicial: comprobación local del 7 de octubre de 2026

La migración `001_initial` crea once tablas de catálogo, la tabla de revisión Alembic y la vista `track_details`. Su exportación [migrations/001_initial.sql](migrations/001_initial.sql) coincide con el esquema aplicado en línea. El catálogo usa contratos Python sin Qt, un lector Mutagen y un repositorio SQLAlchemy.

| Comprobación | Resultado |
| --- | --- |
| Suite completa local | 73 pruebas correctas: entorno, lector, migraciones y catálogo |
| Ruff, formato y mypy estricto | Correctos; 21 archivos de código comprobados por mypy |
| SQL inicial frente a migración Alembic | Mismas tablas, restricciones, índices y vista |
| Wheel instalado con dependencias y hashes del lock, fuera del checkout | Migración empaquetada ejecutada correctamente; FK activadas y revisión `001_initial` |
| Metadatos ausentes en FLAC/MP3 sintéticos y en el catálogo | Campos `NULL`, colecciones vacías; importación y consulta sin excepciones |
| Carátula incrustada, preferencia frontal y alternativa `album.jpg` | Cubiertas por pruebas sintéticas |
| Importación repetida del FLAC proporcionado | Un solo archivo y una sola pista; identificadores conservados |
| Integridad del catálogo local | `integrity_check=ok`; `foreign_key_check` sin filas |
| FLAC original | SHA-256 idéntico antes y después; ninguna escritura |

La base local `data/trackfolio.sqlite3` contiene “Run If You Can”, de Accept, álbum “Breaker”, año 1981, pista 3/10, disco 1/1 y género Heavy Metal. Sus once etiquetas textuales se conservan en `raw_tags`; las líricas y el artista de álbum están ausentes. La carátula JPEG incrustada de 500 × 500 y 385192 bytes se conserva en un BLOB y sus bytes coinciden con los del FLAC.

La matriz anterior corresponde a la infraestructura inicial. La base, la música y la carátula real están excluidas de Git. Tras la validación de esta fase por el usuario, se implementó el visor descrito a continuación.

## GUI del catálogo: 7 de octubre de 2026

La ventana consulta SQLite en modo de sólo lectura, mediante `ListTrackSummaries` y `GetTrack`. El listado no recupera portadas, líricas ni etiquetas originales; el detalle recupera esos datos sólo para la selección. Los widgets y el controlador no importan SQLAlchemy ni Mutagen. Se incluyen fuentes Inter 4.1, licencia, SVG propios y QSS, con un manifiesto de hashes.

| Comprobación local | Resultado |
| --- | --- |
| Suite completa, GUI con `offscreen` | 122 pruebas correctas |
| Núcleo en entorno limpio sin PySide6 | 101 pruebas correctas; 2 módulos GUI omitidos |
| Ruff, formato, mypy | Correctos; 33 archivos de código comprobados por mypy |
| Ventana del producto, eventos y detalle en Wayland | Correctos |
| Ventana del producto, eventos y detalle en X11 | Correctos |
| Diagnóstico `offscreen` | Correcto; no acredita escritorio real |
| BD de ejemplo frente a campos de la ventana | Coinciden canción, artista, álbum, año, numeración, género, portada y líricas vacías |
| Capturas a escalas 100 %, 150 % y 200 % | Generadas con los datos esperados; distribución y portada revisadas localmente |
| Selección y actualización asíncronas | Descartan respuestas antiguas, preservan intención reciente y limpian detalle si desaparecen filas |
| Catálogo vacío, desconocido, inexistente o inaccesible | Estados recuperables; no se crea ni migra una base al abrirla |
| Widget tests | Selección, copia, campos vacíos, portada inválida/proporcional y controles de ventana |
| Wheel y sdist | Construidos con fuentes, licencia, iconos, QSS y migraciones |
| Wheel instalado fuera del checkout | Núcleo sin Qt y GUI con dependencias/hashes del lock; ventana y datos comprobados |
| Workflow y VS Code | actionlint 1.7.12 y JSON válidos; tareas de inicio y depuración de GUI |

Los catálogos y las capturas con la portada de la muestra se conservan en `data/`, excluido de Git. La GUI permite consultar los datos aunque la música original no exista. El lanzador `trackfolio` se instala mediante `project.gui-scripts`.

Los cuatro jobs de la GUI terminaron correctamente en la [ejecución 37659500266](https://github.com/Evilchuck666/Trackfolio/actions/runs/37659500266), sobre `63f822cbd3298e117a1a864ed24fe9eaadbfda05`, rama `gui`:

| Runner | Resultado del producto |
| --- | --- |
| Ubuntu 24.04 x86-64 | Núcleo sin Qt, GUI offscreen/X11, 122 pruebas, tipos y wheel instalado correctos |
| Windows Server 2022 x86-64 | Núcleo sin Qt, GUI offscreen/nativa, 122 pruebas, tipos y wheel instalado correctos |
| macOS 15 Intel | Núcleo sin Qt, GUI offscreen/nativa, 122 pruebas, tipos y wheel instalado correctos |
| macOS 15 Apple Silicon | Núcleo sin Qt, GUI offscreen/nativa, 122 pruebas, tipos y wheel instalado correctos |

La revisión visual manual de Windows y macOS sigue pendiente. Las pruebas automáticas verifican los campos, las fuentes, los recursos y el arranque; no prueban identidad de píxeles entre pantallas. En Wayland, un compositor que rechace las operaciones de mover/redimensionar activa el marco nativo como alternativa.

## Intervalo compatible de uv: 8 de octubre de 2026

El manifiesto y la preparación admiten `>=0.12.10,<0.13`. La comparación de versiones es numérica y comprueba ambos límites antes de ejecutar los pasos de instalación y sincronización. Se mantienen CPython 3.13.15, PySide6 6.11.2, `uv_build==0.12.10` y el contenido de `uv.lock`.

Máquina de esta comprobación: Artix Linux x86-64, glibc 2.44, sesión X11. El uv del sistema es 0.12.23; las comprobaciones con 0.12.10 usan `uv tool run --from uv==0.12.10` sin sustituirlo.

| Comprobación local | Resultado |
| --- | --- |
| Preparación GUI con uv 0.12.10 y 0.12.23 | Correcta con `offscreen`, desde el mismo lock |
| Suite completa con uv 0.12.10 | 152 pruebas correctas |
| Suite completa con uv 0.12.23 | 152 pruebas correctas |
| Pruebas de preparación | 40 correctas; incluyen límites, parches posteriores, comparación numérica, rangos inválidos y mensajes de instalación |
| Ruff, formato y mypy estricto | Correctos; 33 archivos de código comprobados por mypy |
| Ventana del producto y eventos en X11 con uv 0.12.23 | Correctos; diagnóstico GUI sin errores |
| Wheel y distribución de fuentes con uv 0.12.23 | Construidos correctamente con el backend fijado |
| Workflow | actionlint 1.7.12 correcto; YAML y ocho combinaciones únicas comprobados |

La matriz de GitHub Actions queda configurada para uv 0.12.10 y 0.12.23 en las cuatro plataformas existentes. Estos ocho jobs todavía no se han ejecutado en GitHub Actions con los cambios del intervalo; los resultados multiplataforma anteriores corresponden a las revisiones enlazadas en sus secciones.

## Preparación desde un clon o ZIP: 8 de octubre de 2026

`setup.sh` y `setup.ps1` inician la preparación sin exigir Python ni uv en `PATH`. Reutilizan un uv compatible o descargan la versión mínima en `.tools/uv`, sin sustituir la instalación del sistema ni editar perfiles del shell. `scripts/setup.py` comprueba las bibliotecas gráficas, delega el entorno Python en `bootstrap.py` y propone preparar Git y VS Code. Las instalaciones del sistema requieren confirmación. Las tareas de VS Code utilizan los mismos lanzadores.

Las comprobaciones locales se realizaron en el mismo Artix Linux x86-64 de la sección anterior. Para probar el lanzador PowerShell se utilizó PowerShell 7.6.6 descargado en `/tmp/opencode`, con el SHA-256 contrastado con el publicado por GitHub; no se instaló en el sistema.

| Comprobación local | Resultado |
| --- | --- |
| Suite completa con uv 0.12.10 | 210 pruebas correctas, incluidas las pruebas de PowerShell |
| Suite completa con uv 0.12.23 | 210 pruebas correctas, incluidas las pruebas de PowerShell |
| Pruebas de bootstrap, preparación y lanzadores | 98 correctas; selección de uv, consentimiento, argumentos, rutas Unicode, extracción segura y errores |
| Núcleo en copia limpia sin PySide6 | 189 pruebas correctas; 2 módulos GUI omitidos |
| Lanzador Bash con el uv del sistema | Preparación GUI correcta con `offscreen` y X11 (`xcb`) |
| Lanzador PowerShell 7.6.6 con uv del sistema, sobre Linux | Preparación GUI `offscreen` correcta; no acredita Windows |
| Copia sin uv ni Python en `PATH`, ruta con espacios y Unicode | Descarga real de uv 0.12.10 en `.tools/uv`, creación de `.venv` y diagnóstico GUI `offscreen` correctos |
| Preparación repetida en esa copia | Correcta dos veces; mismo lock, perfil y binario uv del sistema; sin recibo ni instalación uv de usuario |
| Intérprete y paquetes de esa copia | CPython administrado y caché de paquetes preexistentes reutilizados; no se acredita una descarga desde cachés vacías |
| Música y catálogo marcadores durante la preparación del núcleo | Bytes conservados; sin modificaciones del lock |
| Descarga y extracción reales de VS Code oficial para Linux | Correctas; CLI 1.141.0 ejecutada desde una carpeta temporal, sin modificar el editor ni sus extensiones del sistema |
| Extensiones recomendadas | Instalación y avisos por extensiones no disponibles cubiertos por pruebas con CLI simulada |
| Ruff, formato y mypy estricto | Correctos; 35 archivos de código comprobados por mypy |
| Sintaxis Bash y ShellCheck | Correctos |
| Wheel y distribución de fuentes | Construidos correctamente |
| Workflow | YAML válido y actionlint 1.7.12 correcto |

La CI queda configurada para usar los lanzadores en los ocho jobs; Windows utiliza Windows PowerShell 5.1. Linux y Windows con uv 0.12.10 añaden una preparación inicial del núcleo sin uv ni Python en `PATH`, repetida dos veces. **Estos cambios todavía no se han ejecutado en GitHub Actions.** Quedan pendientes la comprobación real de Windows/macOS, sus descargas del editor y la revisión manual de su integración con VS Code. No se han instalado paquetes del sistema durante las comprobaciones locales: la propuesta y la autorización de esas instalaciones se prueban con simulaciones.

## Importación gráfica y generación de catálogo: 9 de octubre de 2026

Implementado el [plan de importación](docs/import-plan.md): botón **Importar música…**
y atajo `Ctrl+I`, carpeta recursiva FLAC/MP3, creación de `.tfo` o actualización del
catálogo abierto, progreso, cancelación e informe de incidencias. El núcleo permanece
independiente de Qt. No se cambiaron el esquema, las dependencias ni `uv.lock`.

Comprobaciones locales en Linux x86-64, glibc 2.44, sesión Wayland, uv 0.12.10,
CPython 3.13.15 y PySide6 6.11.2:

| Comprobación | Resultado observado |
| --- | --- |
| Suite completa con GUI | **291 passed, 4 skipped**; los cuatro omitidos necesitan PowerShell, ausente en esta máquina. |
| Ruff y formato | Correctos; 68 archivos con formato comprobado. |
| mypy estricto | Correcto sobre 39 archivos de código. |
| Núcleo desde wheel instalado fuera del checkout, sin PySide6 | **247 passed, 8 skipped**; cuatro módulos GUI omitidos por ausencia de Qt y cuatro pruebas por ausencia de PowerShell. |
| Lotes con audio temporal controlado y lector Mutagen real | Creación, reimportación, IDs estables, campos eliminados, portadas y archivos corruptos comprobados. |
| Errores y cancelación | Vacío/sin audio válido, permisos, bloqueo SQLite real, rollback, destino desconocido, reserva exclusiva y limpieza propia comprobados. |
| GUI y ciclo de vida | Lecturas previas terminan antes del escritor; segunda importación bloqueada; selección conservada; cancelación parcial, disposición y salida directa de QApplication verificadas con eventos/temporizadores controlados. |
| Diagnóstico del producto | Correcto en `offscreen`, Wayland y `xcb` disponible en la sesión local; importa un FLAC temporal, retira el audio y consulta el resultado. |
| Generación desde el botón en escritorio Wayland con música real | Importada una copia temporal de **To War! / Abbath / Abbath / 2016**, pista **1/10**, disco **1/1**, género **Black Metal**, portada **500 × 500**; original intacto por SHA-256. |
| Revisión visual local | Inspeccionadas capturas del formulario, resultado y catálogo en Wayland; renders Qt `offscreen` de tamaño mínimo con Unicode e incidencias largas sin recortes en los diálogos. |
| Wheel y distribución de fuentes | Construidos; contienen módulos nuevos, diálogo, icono, estilos y migraciones. Comprobados 12 hashes de recursos y 54 hashes RECORD. |
| Probe del wheel con GUI desde un directorio ajeno | `offscreen`, Fusion, eventos e importación correctos (`imported=true`). |

La comprobación de música real utilizó una copia en un directorio temporal y un catálogo
nuevo. No modificó el archivo original ni los catálogos de trabajo. Las capturas y bases
de validación permanecen fuera del repositorio.

La instalación aislada utilizó requisitos exportados con `uv export --locked`, hashes y
`--no-deps`; el wheel se instaló también con `--no-deps`. El entorno temporal se eliminó.
Las comprobaciones del checkout utilizaron `uv run --locked --extra gui`.

La matriz existente de GitHub Actions incorpora estas pruebas y verifica los módulos y
la importación desde el wheel. Sus resultados multiplataforma, tras corregir las pruebas,
se registran en la sección de corrección del 9 de octubre. Quedan pendientes la revisión
visual manual y la interacción real de Windows/macOS.
Los resultados `offscreen` no acreditan un escritorio; los backends Wayland/`xcb`
comprobados aquí corresponden únicamente a esta máquina Linux.

## Artistas únicos y consolidación: 9 de octubre de 2026

Implementado el [plan de identidad de artistas](docs/artist-identity-plan.md). La revisión
`002_unique_artists` comparte cada nombre exacto en todo el catálogo y consolida sus filas
anteriores conservando el menor ID y todas las relaciones. El snapshot y SQL históricos
de `001` permanecen intactos. Las dependencias y `uv.lock` no cambiaron.

Comprobaciones locales con uv 0.12.10, CPython 3.13.15, SQLite 3.53.1 y PySide6 6.11.2:

| Comprobación | Resultado observado |
| --- | --- |
| Suite completa del checkout, GUI `offscreen` | **335 passed, 4 skipped**; los cuatro omitidos requieren PowerShell, ausente. |
| Ruff, formato y mypy estricto | Correctos; 73 archivos con formato comprobado y 42 archivos de código en mypy. |
| Identidad global y corrección Abbath → Accept | Reutiliza el artista entre álbumes, carpetas, bibliotecas y pistas sin álbum; conserva IDs y deja otros créditos intactos. |
| Esquema y migración poblada | Igualdad exacta, créditos de pista/álbum, roles, posiciones, `external_id`, artistas sin referencias, BLOBs y etiquetas originales comprobados. |
| Fallos y compatibilidad | Rollback de datos/índice/revisión, respaldo fallido, SQLite WAL, actualización concurrente, índices debilitados y revisiones desconocidas comprobados. |
| Apertura y formulario | Lectura `001`/`002` sin cambios; validación y lote vacío no migran. La integración GUI actualiza al abrir el escritor y reabre con selección conservada. |
| SQL histórico y vigente | Ambos coinciden con su revisión aplicada en línea; `002_current.sql` se genera desde la cadena empaquetada. |
| Consolidación de una copia del catálogo real | **13 → 2 artistas**, Abbath ID 1 y Accept ID 3; todas las demás filas y valores de la vista conservados. Respaldo válido y repetición sin cambios de bytes ni otra copia. |
| Catálogo de trabajo actualizado | `data/database.tfo` en `002_unique_artists`; **139 pistas, 139 archivos, 13 álbumes y 139 créditos de pista** conservados. `foreign_key_check` vacío e `integrity_check=ok`. |
| Respaldo del catálogo de trabajo | `data/database.tfo.001_initial.99fd2fa0fa7442d1b84d67ad03bc0364.bak`, validado contra los datos consolidados. |
| Prueba de volumen temporal | Actualización completa con respaldo de 10.000 artistas y 10.000 créditos en 0,052 s en esta máquina; el índice auxiliar se elimina tras la migración. |
| Wheel y sdist | Construidos y verificados fuera del checkout, con esquema vigente y migración `002`. |
| Núcleo contra wheel instalado, sin PySide6 | **290 passed, 8 skipped**; cuatro módulos GUI omitidos y cuatro pruebas PowerShell. |
| Bloque de verificación de CI del wheel ejecutado localmente | Generación, importación, reimportación y actualización de `001` con respaldo e idempotencia correctos. Dependencias del lock con hashes. |
| Diagnóstico gráfico | Producto correcto en `offscreen` y Wayland; wheel GUI correcto en `offscreen`, Fusion, eventos e importación confirmados. |

La comparación del catálogo real cubrió todas las tablas y la vista, incluidas carátulas
y `raw_tags`; sólo cambiaron las filas duplicadas de artistas, sus referencias y la revisión.
La migración no relee ni escribe música. Catálogo y respaldo permanecen excluidos de Git.
La edición de créditos desde la GUI sigue pendiente; se comprobó la corrección mediante
reimportación de metadatos corregidos.

La matriz multiplataforma incorpora los módulos nuevos y la verificación del wheel.
Los resultados de Windows/macOS constan en la sección siguiente. Su revisión visual manual
sigue pendiente; Wayland acredita únicamente esta máquina.

## Corrección de pruebas multiplataforma: 9 de octubre de 2026

La [ejecución 37916069251](https://github.com/Evilchuck666/Trackfolio/actions/runs/37916069251),
sobre `8a755c8`, pasó en Linux y macOS Intel con ambas versiones de uv. Windows falló en
una prueba del núcleo, y macOS Apple Silicon tuvo esperas agotadas en la integración GUI.

En Windows, la preparación de `test_existing_migration_target_disappearing_is_not_recreated`
dejaba abierta su conexión SQLite: el contexto de conexión confirma o revierte la
transacción, pero no cierra el archivo. Se añadió cierre explícito a las conexiones de
`test_database.py`, manteniendo commit/rollback, y una regresión que retiene una referencia
a la conexión para comprobar que se cerró también en Linux.

En Apple Silicon, los fallos aparecían al iniciar otra importación tras consultas previas.
El mismo timeout se reprodujo localmente con `sys.setswitchinterval(0.1)`: la espera que
alternaba `processEvents()` y `QTest.qWait(5)` impedía avanzar a los trabajadores con esa
planificación. Las esperas usan ahora `QEventLoop` y temporizadores Qt, con el mismo límite
de cinco segundos. La prueba de importación reentrante cubre los intervalos de 0,005 y
0,1 segundos y restaura el valor anterior. No se modificó el código del producto, el
catálogo ni el entorno bloqueado.

| Comprobación local | Resultado |
| --- | --- |
| Pruebas de base e integración de importación | **34 passed**. |
| Suite completa, GUI `offscreen` | **337 passed, 4 skipped**; PowerShell ausente. |
| Ruff, formato y mypy | Correctos; 73 archivos con formato y 42 archivos de código en mypy. |

La [ejecución 37919647833](https://github.com/Evilchuck666/Trackfolio/actions/runs/37919647833)
confirmó la corrección `1b68511` en las seis combinaciones de Linux y macOS. Windows superó
la prueba del núcleo y llegó a dos errores de GUI que antes no se habían ejecutado:

- El selector Qt devuelve rutas con `/`, mientras `str(WindowsPath)` usa `\\`. La prueba
  compara ahora objetos `Path`, manteniendo la comprobación de ruta y Unicode.
- El catálogo antiguo del test almacenaba la raíz con `str(music)`, en lugar de
  `music.as_posix()`, que usa el repositorio. El fixture utiliza la representación real;
  se mantienen las expectativas de IDs, artistas y una canción creada y otra actualizada.
  Sus conexiones SQLite también se cierran explícitamente.

Estos cambios se publicaron en `5850021`, rama `generate-db`. Sus **25 pruebas afectadas**,
Ruff, formato y mypy pasan localmente. La [ejecución 37920075123](https://github.com/Evilchuck666/Trackfolio/actions/runs/37920075123),
sobre `58500218e7b11e22836f7036f593eed3a20a242e`, terminó con **los ocho jobs correctos**:

| Plataforma, con uv 0.12.10 y 0.12.23 | Núcleo sin Qt | Suite con GUI |
| --- | --- | --- |
| Linux x86-64 | 295 passed, 4 skipped | 341 passed |
| Windows x86-64 | 283 passed, 16 skipped | 329 passed, 12 skipped |
| macOS Intel | 295 passed, 4 skipped | 341 passed |
| macOS Apple Silicon | 295 passed, 4 skipped | 341 passed |

Los módulos Qt se omiten en las suites del núcleo. En Windows también se omiten los
lanzadores Unix y el caso de un nombre de archivo con `?`, no admitido por ese sistema.
No se omitieron las pruebas corregidas. Ruff, formato, mypy, los diagnósticos gráficos
`offscreen`/nativos y la verificación del wheel instalado fuera del checkout pasaron.
La revisión visual manual de Windows/macOS sigue pendiente.

## Edición de canciones en el catálogo: 9 de octubre de 2026

Implementado el [plan de edición](docs/edit-plan.md): **Editar**, **Guardar** y
**Cancelar** para los diez campos del detalle, artistas y géneros como listas ordenadas,
validación junto al campo y navegación con cambios pendientes. Las correcciones se
guardan en SQLite y funcionan sin el archivo musical. Reimportar sustituye los valores
manuales por las etiquetas del archivo; el formulario explica esta consecuencia.

La corrección Abbath → Accept reutiliza la identidad exacta del artista y cambia sólo
la canción seleccionada. Título/año de álbum reasignan una agrupación sin modificar
otras pistas; pistas compartidas se copian para el archivo seleccionado. Se preservan
audio, portada, `raw_tags` y roles adicionales. No cambian las dependencias, `uv.lock`,
las revisiones históricas ni el esquema vigente `002_unique_artists`.

Comprobaciones locales en Linux x86-64, glibc 2.44, CPython 3.13.15, uv 0.12.10,
PySide6/Qt 6.11.2 y SQLite 3.53.1:

| Comprobación | Resultado observado |
| --- | --- |
| Suite completa del checkout, Qt `offscreen` | **426 passed, 4 skipped**; los cuatro omitidos requieren PowerShell, ausente. |
| Edición de núcleo/SQLite y limpieza del caso de uso | **48 pruebas**: patch parcial, vaciados, validación, identidad exacta, aislamiento, conflictos, rollback, sugerencias y respaldo de `001`. |
| Coordinación GUI con SQLite temporal | **23 pruebas**: guardar/reabrir, cancelar, guardas de navegación, cierre cooperativo, conflictos y respuestas atrasadas. |
| Ruff y formato | Correctos; **82 archivos** comprobados. |
| mypy estricto | Correcto sobre **46 archivos** de código. |
| Diagnóstico del producto | Importación y edición confirmadas en `offscreen`, Wayland y X11 (`xcb`), con Fusion y 12 recursos verificados. |
| Ventana nativa Wayland | Guardar título y artista desde los controles, releer SQLite, cancelar otro borrador y mantener la selección; catálogo fuente y FLAC temporal originales intactos por SHA-256. |
| Revisión de capturas | Inspeccionados los controles en la ventana Wayland y los renders a 1320 × 840 y 960 × 640; listas, botones y scroll disponibles. |
| Wheel y distribución de fuentes | Construidos; módulos nuevos y recursos incluidos. Ejecutado localmente el bloque de verificación del wheel de la matriz CI. |
| Wheel instalado sin checkout ni Qt | Generación, importación, edición por caso de uso, relectura y migración con respaldo correctas; PySide6 ausente. |
| Suite desde el wheel instalado sin Qt | **341 passed, 10 skipped**; seis módulos GUI omitidos por ausencia de PySide6 y cuatro pruebas por ausencia de PowerShell. |
| Wheel GUI instalado fuera del checkout | Probe con `events=true`, `imported=true` y `edited=true`, backend `offscreen` y Fusion; edita después de retirar el audio y preserva etiquetas originales y portada. |

Las comprobaciones utilizaron bases y contenedores FLAC temporales controlados; no
modificaron música ni catálogos personales. Las capturas se conservaron fuera del
repositorio. El respaldo del primer guardado de `001`, la detección de cambios externos
y el resultado confirmado ante un fallo posterior de liberación tienen pruebas específicas.

Se corrigieron y cubrieron dos carreras: una respuesta de actualización anterior a
**Editar** ya no reemplaza el borrador ni abre un diálogo inesperado; una continuación
de navegación posterior al guardado se descarta si un observador ya abrió otro catálogo.
Las esperas nuevas de integración usan el bucle nativo de Qt y las conexiones SQLite
se cierran explícitamente para conservar las correcciones previas de macOS y Windows.

La matriz existente incorpora las pruebas nuevas y exige la edición en los diagnósticos
y el wheel instalado. La primera ejecución remota se recoge en la sección siguiente.
La revisión visual manual de Windows y macOS sigue pendiente.
Las pruebas `offscreen` no acreditan un escritorio real y los backends nativos comprobados
en esta entrega corresponden únicamente a esta máquina Linux.

## Corrección del diálogo de edición en macOS: 9 de octubre de 2026

La [ejecución 37935958225](https://github.com/Evilchuck666/Trackfolio/actions/runs/37935958225),
sobre `60e8948`, pasó en Linux y Windows con ambas versiones de uv. Las cuatro
combinaciones de macOS (Intel y Apple Silicon) fallaron únicamente en
`test_real_unsaved_dialog_cancel_restores_selection_and_draft`: esperaba el título
«Cambios sin guardar» y recibía una cadena vacía.

[Qt documenta](https://doc.qt.io/qt-6/qmessagebox.html#setWindowTitle) que macOS ignora
el título de `QMessageBox`. La prueba comprueba ahora el mensaje del diálogo real,
«Hay cambios sin guardar en esta canción.», y sigue pulsando **Cancelar** y comprobando
que se conservan la selección y el borrador y que SQLite permanece sin cambios.
No se omiten pruebas ni se modifica el comportamiento del producto.

Comprobaciones locales: **39 pruebas** de widgets e integración de edición correctas;
suite completa `offscreen` con **426 passed, 4 skipped** (PowerShell ausente); Ruff,
formato de 82 archivos y mypy sobre 46 archivos de código correctos.
La [ejecución 37937722182](https://github.com/Evilchuck666/Trackfolio/actions/runs/37937722182),
sobre `33b6813`, confirmó la corrección: **430 pruebas correctas** en las cuatro
combinaciones de macOS (Intel y Apple Silicon, uv 0.12.10 y 0.12.23). Linux también
pasó con ambas versiones. Los diagnósticos gráficos y la verificación del wheel
pasaron en esas seis combinaciones.

Windows llegó a otro fallo en ambas variantes: la prueba de guardar y continuar con
**Actualizar** esperaba el guardado, pero no la finalización de la actualización.
Podía observar un estado intermedio sin tareas pendientes y salir del bucle; al
comenzar la actualización aplazada, su comprobación final volvía a ser falsa.
La prueba espera ahora también la señal de detalle cargado posterior a **Actualizar**
y comprueba que el guardado produjo un resultado. Se conserva el límite de cinco
segundos y el código del producto no cambia. El orden de eventos se reprodujo con
Qt y SQLite reales: el mensaje de timeout apareció en **0,026 segundos** al comenzar
el trabajo de actualización antes de salir del bucle de espera. La suite completa
local sigue con **426 passed, 4 skipped**, y Ruff, formato y mypy pasan.
La [ejecución 37939283014](https://github.com/Evilchuck666/Trackfolio/actions/runs/37939283014),
sobre `efb9935a9177b509b9bd2962a2f21c46656cc400`, terminó con **los ocho jobs correctos**:

| Plataforma, con uv 0.12.10 y 0.12.23 | Núcleo sin Qt | Suite con GUI |
| --- | --- | --- |
| Linux x86-64 | 345 passed, 6 skipped | 430 passed |
| Windows x86-64 | 333 passed, 18 skipped | 418 passed, 12 skipped |
| macOS Intel | 345 passed, 6 skipped | 430 passed |
| macOS Apple Silicon | 345 passed, 6 skipped | 430 passed |

Los seis módulos GUI se omiten cuando Qt no está instalado. En Windows se conservan
las omisiones de los lanzadores Unix y del nombre de archivo con `?`; las pruebas
corregidas se ejecutan en todas las plataformas. Ruff, formato, mypy, diagnósticos
gráficos nativos y `offscreen` y la verificación del wheel instalado fuera del checkout
pasaron. La revisión visual manual de Windows y macOS sigue pendiente.

## Repositorio

Git inicializado con rama `main`, `origin` y seguimiento de `origin/main`. La infraestructura y documentación están subidas a [Evilchuck666/Trackfolio](https://github.com/Evilchuck666/Trackfolio), un repositorio privado. El workspace se abre mediante `code Trackfolio.code-workspace`; la preparación para otro PC está en [README.md](README.md).

## Actualización a uv 0.13.4 (2026-10-29)

Se han instalado los binarios oficiales `uv` y `uvx` 0.13.4 en `.tools/uv`.
El requisito del proyecto pasa a `>=0.13.4,<0.14`; los lanzadores leen ese
requisito para seleccionar o descargar uv. El backend permanece fijado en
`uv_build==0.12.10` y `uv.lock` no ha cambiado.

Comprobaciones locales en Linux con CPython 3.13.15:

- `uv lock --check --offline`: correcto con uv 0.13.4.
- Preparación GUI mediante `setup.sh`, diagnóstico Qt/Fusion `offscreen`,
  importación y edición: correctos con uv 0.13.4.
- Suite completa con el uv local y `QT_QPA_PLATFORM=offscreen`: 426 pruebas
  correctas y 4 omitidas porque PowerShell no está instalado. La suite GUI
  requiere ejecución fuera del sandbox en esta máquina.
- Ruff, comprobación de formato y mypy: correctos.
- Wheel y distribución de fuentes: construidos con el uv local 0.13.4.

El workflow se renombra de `checks.yml` a `release.yml`, con uv 0.13.4 en
las cuatro plataformas. La preparación inicial de Linux y Windows comprueba
las versiones de ambos binarios locales. La ejecución de esta revisión en
GitHub Actions y la revisión visual manual de Windows/macOS siguen pendientes.
