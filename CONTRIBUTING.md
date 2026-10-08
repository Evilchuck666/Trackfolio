# Contribuir a Trackfolio

## Incorporación

Instala **uv >=0.12.10 y <0.13** y Git siguiendo [docs/environment.md](docs/environment.md), clona el repositorio y prepara el entorno desde la raíz. Una versión compatible ya instalada, como 0.12.23, no necesita sustituirse:

```sh
uv run --no-project --python 3.13.15 python scripts/bootstrap.py --gui
```

Usa `--core` para desarrollar sin Qt. Abre `Trackfolio.code-workspace` en VS Code y selecciona el intérprete local `.venv` si el editor no lo detecta.

El entorno usa CPython 3.13.15 administrado por uv y dependencias bloqueadas en `uv.lock`. No instales paquetes del proyecto en el Python global ni copies `.venv` desde otro equipo. Los comandos `uv run` no requieren activar el entorno.

## Cambios de código

Respeta [docs/architecture.md](docs/architecture.md): el dominio y los casos de uso no importan Qt, SQLAlchemy ni Mutagen. Los modelos ORM y widgets pertenecen a adaptadores. Toda interfaz utiliza los mismos casos de uso.

Usa `pathlib` para las rutas. Evita rutas absolutas de un desarrollador, comandos dependientes de Bash, `shell=True` y accesos a música o bases de datos reales en las pruebas. Los scripts compartidos deben funcionar en Windows, macOS y GNU/Linux.

Antes de proponer un cambio ejecuta las comprobaciones pertinentes:

```sh
uv run --locked ruff check .
uv run --locked ruff format --check .
uv run --locked mypy
uv run --locked pytest
```

Si cambias dependencias o diagnósticos, repite también `doctor.py --core` y, cuando corresponda, `doctor.py --gui` con el extra `gui`. Registra el SO, la arquitectura y el backend gráfico de las pruebas; separa `offscreen` de X11, Wayland y escritorios nativos. No declares una plataforma validada basándote solo en otra.

## Actualizar dependencias

Los requisitos directos se declaran en `pyproject.toml`; las versiones resueltas están en `uv.lock`. Los comandos habituales usan `--locked`, para que un lock desactualizado falle sin modificarlo. No uses `--frozen` para ocultar una discrepancia.

Para añadir una dependencia del núcleo, de la GUI o de desarrollo:

```sh
uv add paquete
uv add --optional gui paquete
uv add --group dev paquete
```

Estos comandos son ejemplos alternativos; sustituye `paquete` y ejecuta el que corresponda. Para actualizar una dependencia ya existente de forma deliberada:

```sh
uv lock --upgrade-package nombre-del-paquete
uv sync --locked --extra gui --group dev
uv run --locked --extra gui python scripts/doctor.py --gui
```

Revisa el diff del manifiesto y del lock, ejecuta las comprobaciones y sube ambos archivos cuando cambien. Las actualizaciones de parche de uv dentro de `>=0.12.10,<0.13` no requieren editar el requisito; verifica la preparación y las pruebas con la versión elegida. Ampliar ese rango o actualizar CPython, el backend de construcción o PySide6 requiere revisar la configuración, los scripts y la documentación pertinentes, y verificar nuevamente la matriz. `uv_build==0.12.10` es el backend de construcción, no una exigencia sobre el ejecutable uv instalado. No amplíes `requires-python` sin validar el nuevo intérprete.

## Git y datos locales

Configura tu identidad al clonar si no la tienes configurada:

```sh
git config --local user.name "Tu nombre"
git config --local user.email "tu-correo@example.com"
git config --local core.autocrlf false
git config --local pull.ff only
```

`.gitattributes` define los finales de línea del repositorio y `.editorconfig` mantiene el formato básico. `.gitignore` excluye entornos, cachés, música, bases de datos y secretos. No fuerces su inclusión. Los futuros datos de prueba deberán ser pequeños, artificiales o redistribuibles, y añadirse explícitamente.

Incluye en la descripción del cambio el comportamiento que modifica y las comprobaciones ejecutadas. Esta fase prepara el entorno: las nuevas funcionalidades musicales y las interfaces se desarrollarán en cambios posteriores.
