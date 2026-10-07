# Trackfolio

Trackfolio será una aplicación multiplataforma para administrar metadatos de bibliotecas FLAC y MP3. Usará Python, Qt 6 mediante PySide6 y SQLite mediante SQLAlchemy. El dominio y los casos de uso serán independientes de la GUI, para poder añadir interfaces CLI/TUI o un servidor con frontend web.

Este repositorio contiene el entorno reproducible, las migraciones SQLite y la importación y consulta de metadatos FLAC/MP3. El catálogo conserva los campos ausentes en blanco y las carátulas incrustadas o procedentes de `album.jpg`. La GUI será la siguiente interfaz de producto, después de revisar esta primera base de datos; la edición de etiquetas sigue pendiente.

## Preparar un PC

Se necesitan Git, acceso a Internet durante la primera preparación y **uv 0.12.10**. El proyecto obtiene **CPython 3.13.15 administrado por uv**; el Python del sistema no necesita coincidir. Consulta las [instrucciones de instalación y requisitos del sistema](docs/environment.md) si falta alguna herramienta.

Clona el repositorio y entra en su raíz. En Windows puedes usar `%USERPROFILE%\projects\Trackfolio`; la ubicación no está fijada en la configuración.

```sh
git clone https://github.com/Evilchuck666/Trackfolio.git
cd Trackfolio
uv run --no-project --python 3.13.15 python scripts/bootstrap.py --gui
```

El repositorio es privado: Git necesita una cuenta con acceso y un gestor de credenciales configurado. Si usas GitHub CLI, ejecuta `gh auth login` y `gh auth setup-git` antes de clonarlo. No guardes credenciales en el proyecto.

La preparación comprueba uv, instala el Python fijado, crea `.venv`, sincroniza las dependencias desde `uv.lock` y ejecuta el diagnóstico. Un requisito obligatorio que falle devuelve un código de salida distinto de cero. No hace falta activar `.venv`.

Para trabajar únicamente en el núcleo, sin instalar Qt:

```sh
uv run --no-project --python 3.13.15 python scripts/bootstrap.py --core
```

## Comprobar el entorno

Desde la raíz del proyecto:

```sh
uv run --locked --extra gui python scripts/doctor.py --gui
uv run --locked ruff check .
uv run --locked ruff format --check .
uv run --locked mypy
uv run --locked pytest
```

La comprobación GUI abre una ventana mínima de diagnóstico y procesa eventos. En Linux puedes elegir explícitamente X11 con `--platform xcb` o Wayland con `--platform wayland`. Para una máquina sin escritorio usa `--platform offscreen`; esa comprobación no valida un escritorio real.

Para comprobar únicamente el núcleo:

```sh
uv sync --locked --group dev
uv run --locked python scripts/doctor.py --core
```

`uv.lock` bloquea las versiones de dependencias y `--locked` exige que corresponda con `pyproject.toml`. Cada PC debe recrear su propia `.venv`. Comparte las fuentes mediante Git; conserva las bases de datos, la música y la configuración local fuera del repositorio.

## Abrir en VS Code

```sh
code Trackfolio.code-workspace
```

Acepta las extensiones recomendadas. Si el editor utiliza otro intérprete, ejecuta **Python: Select Interpreter** y selecciona el de `.venv`. Las tareas del workspace preparan y diagnostican el entorno, y ejecutan las comprobaciones de desarrollo mediante `uv`.

## Revisar el catálogo

Desde la raíz del proyecto, importa un archivo sin modificarlo:

```sh
uv run --locked python scripts/import_audio.py "ruta/a/cancion.flac" --database data/trackfolio.sqlite3
```

Abre `data/trackfolio.sqlite3` en SQLiteBrowser y consulta la vista `track_details`. La [guía de la base de datos](docs/database.md) explica las tablas, los campos ausentes y la revisión de carátulas. El SQL inicial está en [migrations/001_initial.sql](migrations/001_initial.sql); la base local y la música están excluidas de Git.

## Compatibilidad prevista

| Plataforma GUI | Base inicial |
| --- | --- |
| Windows | Windows 10 1809+ o Windows 11, x86-64 |
| macOS | macOS 13+, Intel x86-64 o Apple Silicon ARM64 |
| GNU/Linux | x86-64, glibc 2.34+, escritorio X11 o Wayland y bibliotecas gráficas requeridas |

La disponibilidad de un wheel compatible no demuestra que la GUI funcione en cada escritorio. Las comprobaciones ejecutadas y las pendientes se registran en [VALIDATION.md](VALIDATION.md). Alpine/musl, Windows ARM64 y Linux ARM64 quedan fuera de esta primera matriz.

Consulta [el entorno portable](docs/environment.md), [la arquitectura](docs/architecture.md), [la guía de contribución](CONTRIBUTING.md) y [el plan original](PLAN.md).
