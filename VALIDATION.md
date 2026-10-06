# Validación del entorno de Trackfolio

Fecha: 6 de octubre de 2026. Estas comprobaciones corresponden a la infraestructura inicial, no al editor musical ni a una GUI de producto, que todavía están pendientes de desarrollo.

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

## Matriz automatizada

El workflow comprueba instalación limpia del núcleo sin Qt, instalación GUI desde el lock, diagnósticos, 23 pruebas, Ruff, mypy, construcción y recursos del wheel. Linux añade X11 bajo Xvfb; Windows y macOS comprueban sus backends nativos además de `offscreen`.

| Runner | Arquitectura | Estado |
| --- | --- | --- |
| Ubuntu 24.04 | x86-64 | Correcto: núcleo, Qt offscreen/X11, pruebas y distribución |
| Windows Server 2022 | x86-64 | Correcto: núcleo, Qt offscreen/nativo, pruebas y distribución |
| macOS 15 Intel | x86-64 | Correcto: núcleo, Qt offscreen/nativo, pruebas y distribución |
| macOS 15 Apple Silicon | ARM64 | Correcto: núcleo, Qt offscreen/nativo, pruebas y distribución |

Los cuatro jobs terminaron correctamente en la [ejecución 37457968238 de GitHub Actions](https://github.com/Evilchuck666/Trackfolio/actions/runs/37457968238), sobre la revisión `d201961976d20f78b07d80e6e30071bf28411b77`. Este registro posterior sólo actualiza documentación.

Los runners no cubren todas las versiones mínimas anunciadas ni todos los escritorios. La apariencia del futuro producto, los controles reales y las decoraciones de ventana deberán validarse cuando exista la GUI de Trackfolio.

## Repositorio

Git inicializado con rama `main`, `origin` y seguimiento de `origin/main`. La infraestructura y documentación están subidas a [Evilchuck666/Trackfolio](https://github.com/Evilchuck666/Trackfolio), un repositorio privado. El workspace se abre mediante `code Trackfolio.code-workspace`; la preparación para otro PC está en [README.md](README.md).
