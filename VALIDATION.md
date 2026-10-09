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
la importación desde el wheel. **Esta entrega todavía no se ha ejecutado en GitHub
Actions**. Quedan pendientes Windows/macOS y su revisión visual e interacción real.
Los resultados `offscreen` no acreditan un escritorio; los backends Wayland/`xcb`
comprobados aquí corresponden únicamente a esta máquina Linux.

## Repositorio

Git inicializado con rama `main`, `origin` y seguimiento de `origin/main`. La infraestructura y documentación están subidas a [Evilchuck666/Trackfolio](https://github.com/Evilchuck666/Trackfolio), un repositorio privado. El workspace se abre mediante `code Trackfolio.code-workspace`; la preparación para otro PC está en [README.md](README.md).
