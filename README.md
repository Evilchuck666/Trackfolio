# Trackfolio

Trackfolio es una aplicación multiplataforma para consultar metadatos de bibliotecas FLAC y MP3. Usa Python, Qt 6 mediante PySide6 y SQLite mediante SQLAlchemy. El dominio y los casos de uso son independientes de la GUI, para poder añadir interfaces CLI/TUI o un servidor con frontend web.

La GUI muestra canciones, artistas, álbum, año, numeración, géneros, líricas y portada desde el catálogo. Los campos ausentes quedan vacíos. El importador conserva las carátulas incrustadas o procedentes de `album.jpg` sin modificar la música. La edición de etiquetas y la importación gráfica se abordarán en los siguientes incrementos.

## Preparar un PC

Descarga el repositorio, entra en su raíz y ejecuta un único comando. **No necesitas instalar previamente uv ni Python.** Se necesita Internet durante la primera preparación y un sistema compatible. Esta versión está en la rama `gui`: elige esa rama al descargar el ZIP de GitHub o clónala si ya tienes Git:

```sh
git clone --branch gui https://github.com/Evilchuck666/Trackfolio.git
cd Trackfolio
```

**Linux y macOS:**

```sh
bash setup.sh
```

**Windows, desde PowerShell:**

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\setup.ps1
```

El repositorio es privado: necesitas una cuenta con acceso para descargarlo. Para clonar mediante Git, configura tu gestor de credenciales; si usas GitHub CLI, ejecuta `gh auth login` y `gh auth setup-git`. No guardes credenciales en el proyecto.

La preparación reutiliza un uv compatible (`>=0.12.10,<0.13`, como 0.12.23). Si falta, descarga la versión mínima en `.tools/uv`, **sin sustituir el uv del sistema ni modificar los perfiles del shell**. Obtiene CPython 3.13.15 administrado por uv, crea `.venv`, instala la GUI y las herramientas de desarrollo desde `uv.lock`, y comprueba el entorno.

Si faltan bibliotecas gráficas o Git, propone su instalación y pide permiso. Si no hay VS Code, ofrece descargarlo en `.tools/vscode`; instala las extensiones recomendadas cuando el editor está disponible. No toca música ni catálogos y puedes repetirla. Un requisito obligatorio que falle devuelve un código distinto de cero. Consulta [las opciones y los límites por plataforma](docs/environment.md#preparación-en-un-solo-comando).

Para preparar sólo Python y Qt, sin descargar el editor ni instalar extensiones:

```sh
bash setup.sh --skip-editor
```

Para trabajar únicamente en el núcleo, añade `--core`. En Windows se usan los mismos argumentos después de `-File .\setup.ps1`. No hace falta activar `.venv`.

## Comprobar el entorno

Desde la raíz del proyecto:

```sh
bash setup.sh --run-uv run --locked --extra gui python scripts/doctor.py --gui
bash setup.sh --run-uv run --locked --extra gui ruff check .
bash setup.sh --run-uv run --locked --extra gui ruff format --check .
bash setup.sh --run-uv run --locked --extra gui mypy
bash setup.sh --run-uv run --locked --extra gui pytest
```

`--run-uv` ejecuta un comando con el uv compatible sin repetir la preparación. En Windows sustituye `bash setup.sh` por `powershell -NoProfile -ExecutionPolicy Bypass -File .\setup.ps1`. Si ya tienes uv en `PATH`, los comandos directos `uv run ...` siguen funcionando.

La comprobación GUI abre la ventana del producto con una base temporal y verifica sus campos y portada. En Linux puedes elegir X11 con `--platform xcb` o Wayland con `--platform wayland`. Para una máquina sin escritorio usa `--platform offscreen`; esa comprobación no valida un escritorio real. La tarea de VS Code **Trackfolio: ejecutar pruebas GUI sin pantalla** ejecuta la suite con ese backend.

Para comprobar únicamente el núcleo:

```sh
bash setup.sh --core --skip-editor
```

`uv.lock` bloquea las versiones de dependencias y `--locked` exige que corresponda con `pyproject.toml`. Cada PC debe recrear su propia `.venv` y `.tools`; no copies esas carpetas entre equipos. Comparte las fuentes mediante Git; conserva las bases de datos, la música y la configuración local fuera del repositorio.

## Abrir en VS Code

```sh
bash setup.sh --open-code
```

Esto también funciona cuando el editor se descargó en `.tools/vscode`. Si tienes `code` en `PATH`, puedes abrir directamente `code Trackfolio.code-workspace`. Si el editor utiliza otro intérprete, ejecuta **Python: Select Interpreter** y selecciona el de `.venv`. Las tareas del workspace usan los lanzadores para encontrar uv; las terminales integradas incluyen la copia local en su `PATH`.

## Iniciar la GUI

Desde la raíz, después de preparar el entorno:

```sh
bash setup.sh --run-uv run --locked --extra gui trackfolio
```

Para abrir una base concreta añade `--database "ruta/al/catalogo.tfo"`. La base de ejemplo es local y está excluida de Git: **la preparación deja la aplicación lista, pero no inventa canciones ni crea un catálogo con tu música**. Un clon nuevo necesita importar un archivo o abrir un catálogo existente.

Sin `--database`, se restaura el último catálogo abierto cuando sigue disponible. Para empezar sin restaurarlo, usa `--no-restore`. Puedes abrir otra base con **Abrir catálogo…** y recargar sus registros con **Actualizar**. Selecciona una canción para consultar su detalle; los textos permiten copiar datos y las líricas se muestran como texto plano.

La GUI abre SQLite en modo de sólo lectura. Mostrar los registros no requiere acceder al FLAC/MP3 original: también las imágenes están guardadas en el catálogo. Las fuentes, iconos y estilos se incluyen en el paquete y se cargan sin descargas durante el uso.

En VS Code, ejecuta la tarea **Trackfolio: iniciar GUI con la muestra** o la configuración de depuración **Trackfolio: GUI con catálogo de ejemplo**. Consulta el [plan y su estado](docs/gui-plan.md) y los [resultados comprobados](VALIDATION.md).

## Revisar el catálogo

Desde la raíz del proyecto, importa un archivo sin modificarlo:

```sh
bash setup.sh --run-uv run --locked --extra gui python scripts/import_audio.py "ruta/a/cancion.flac" --database data/database.tfo
```

Abre `data/database.tfo` en SQLiteBrowser y consulta la vista `track_details`. La [guía de la base de datos](docs/database.md) explica las tablas, los campos ausentes y la revisión de carátulas. El SQL inicial está en [migrations/001_initial.sql](migrations/001_initial.sql); la base local y la música están excluidas de Git.

## Compatibilidad prevista

La GUI usa Fusion, una paleta, fuentes e iconos empaquetados y controles de ventana propios. El escalado y el rasterizado pueden variar según la pantalla. Si un compositor Wayland rechaza mover o redimensionar la ventana, se habilita su marco nativo para conservar esas operaciones.

| Plataforma GUI | Base inicial |
| --- | --- |
| Windows | Windows 10 1809+ o Windows 11, x86-64 |
| macOS | macOS 13+, Intel x86-64 o Apple Silicon ARM64 |
| GNU/Linux | x86-64, glibc 2.34+, escritorio X11 o Wayland y bibliotecas gráficas requeridas |

La disponibilidad de un wheel compatible no demuestra que la GUI funcione en cada escritorio. Las comprobaciones ejecutadas y las pendientes se registran en [VALIDATION.md](VALIDATION.md). Alpine/musl, Windows ARM64 y Linux ARM64 quedan fuera de esta primera matriz.

Consulta [el entorno portable](docs/environment.md), [la arquitectura](docs/architecture.md), [la guía de contribución](CONTRIBUTING.md) y [el plan original](PLAN.md).
