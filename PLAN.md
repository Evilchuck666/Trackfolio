# Plan de preparación de Trackfolio

Fecha: 6 de octubre de 2026. Este documento prepara el entorno antes de desarrollar la aplicación.

> Este es el plan original. Su infraestructura ya se ha implementado; los comandos actuales están en README.md y los resultados medidos en VALIDATION.md. La situación de la sección 1 corresponde a la inspección previa.

El resultado de esta fase será un repositorio que se pueda clonar en otro PC, abrir en VS Code y preparar con los mismos comandos de `uv`. Todavía no se implementarán el catálogo musical, el editor de etiquetas ni las interfaces CLI/TUI/web.

## 1. Situación comprobada

| Elemento | Estado en este PC |
| --- | --- |
| Directorio | Existe `/home/evilchuck/projects/Trackfolio` |
| Workspace | Existe `Trackfolio.code-workspace`, con una carpeta relativa `.` |
| Git | Instalado: 2.55.0; el directorio todavía no es un repositorio |
| uv | Instalado: 0.12.10 |
| Python del sistema | CPython 3.14.7 |
| SQLite del sistema | 3.53.4; consulta en memoria comprobada |
| VS Code | Instalado: 1.140.0; extensiones Python, Pylance y depuración disponibles |
| GitHub CLI | Instalado y autenticado como `Evilchuck666` mediante HTTPS |
| Identidad de Git | Nombre y correo configurados; se reutilizarán |
| Repositorio remoto | La consulta de `Evilchuck666/Trackfolio` no encontró un repositorio accesible |

No se han instalado dependencias, inicializado Git ni publicado archivos. La consulta de SQLite verifica el Python del sistema; habrá que repetirla con el intérprete del proyecto. Tampoco se ha comprobado aún que Qt pueda abrir una ventana en este PC.

## 2. Contrato de compatibilidad

La promesa será reproducibilidad en Windows, macOS y GNU/Linux compatibles. Tener cualquier versión de Python 3 y `uv` no basta para ejecutar cualquier versión de Qt.

Base propuesta:

- CPython **3.13.15**, disponible para descarga según el `uv` instalado. Se fijará el parche en `.python-version`, usando Python administrado por `uv` y sin sustituir el Python del sistema. Su instalación se verificará en cada plataforma objetivo.
- `requires-python = ">=3.13,<3.14"` durante la primera etapa. El soporte de otras versiones se ampliará cuando pase la matriz de comprobaciones.
- `uv` **0.12.10**, la versión comprobada en este PC. Se exigirá mediante `tool.uv.required-version`; los cambios de esta herramienta también se registrarán en Git.
- PySide6 **6.11.2** como dependencia opcional de la GUI. SQLAlchemy, Mutagen y las herramientas de desarrollo tendrán versiones resueltas y registradas en `uv.lock` durante la preparación.

La primera matriz objetivo de GUI será Windows 10 1809+/11 x86-64, macOS 13+ Intel y Apple Silicon, y GNU/Linux x86-64 con glibc 2.34+ y escritorio X11 o Wayland compatible. La publicación de wheels no equivale a una prueba de funcionamiento: estas combinaciones tendrán que validarse. Windows ARM64 y Linux ARM64 se incorporarán después de comprobar sus dependencias y disponer de pruebas adecuadas. Alpine/musl y sistemas antiguos quedan fuera de esta primera matriz.

Los mínimos provienen de las [plataformas de Qt 6.11](https://doc.qt.io/qtforpython-6/overviews/qtdoc-supported-platforms.html) y de los [wheels de PySide6 6.11.2](https://pypi.org/project/PySide6/6.11.2/). Los binarios para Linux ARM64 de esta versión requieren glibc 2.39+.

## 3. Directorio y archivos del proyecto

Se conservarán el directorio y el workspace existentes. En otros equipos, la ubicación equivalente será `~/projects/Trackfolio`, o `%USERPROFILE%\projects\Trackfolio` en Windows. El proyecto podrá funcionar desde otra ubicación: ninguna ruta personal formará parte de su configuración compartida.

Estructura prevista; los módulos de aplicación se reservarán sin implementar todavía funcionalidades:

```text
Trackfolio/
├── PLAN.md
├── README.md
├── CONTRIBUTING.md
├── pyproject.toml
├── uv.lock
├── .python-version
├── .gitignore
├── .gitattributes
├── .editorconfig
├── Trackfolio.code-workspace
├── .vscode/
│   ├── extensions.json
│   └── tasks.json
├── .github/workflows/
│   └── release.yml
├── scripts/
│   ├── bootstrap.py
│   └── doctor.py
├── docs/
│   ├── environment.md
│   └── architecture.md
├── src/trackfolio/
│   ├── __init__.py
│   ├── domain/
│   ├── application/
│   ├── infrastructure/
│   ├── interfaces/
│   │   └── gui/
│   └── resources/
└── tests/
```

Se usará un paquete instalable con estructura `src`, para que las importaciones funcionen igual fuera del directorio raíz. El backend de construcción tendrá una versión exacta declarada en `[build-system]`. Se documentará la arquitectura prevista; se añadirán pruebas funcionales cuando haya comportamiento que probar.

`.gitignore` excluirá `.venv`, cachés, resultados de compilación, archivos de configuración local, bases de datos locales y música del usuario. Los datos de prueba deliberadamente incluidos se distinguirán de esos datos locales. `.gitattributes` y `.editorconfig` definirán UTF-8 y LF para código y configuración, con excepciones para archivos que requieran otro tratamiento.

## 4. Dependencias y aislamiento

| Ámbito | Dependencias previstas | Motivo |
| --- | --- | --- |
| Persistencia | SQLAlchemy 2.x y Alembic | Acceso a SQLite y evolución del esquema |
| Metadatos musicales | Mutagen | Lectura/escritura de FLAC y MP3 |
| Directorios de usuario | platformdirs | Ubicación portable de configuración, caché y BD |
| Extra `gui` | PySide6 6.11.2 | Qt 6 sin obligar al núcleo a instalar un escritorio |
| Grupo `dev` | pytest, Ruff y mypy | Pruebas, formato, análisis y tipos |

Mutagen declara soporte para [FLAC y MP3](https://mutagen.readthedocs.io/en/latest/). La edición de metadatos no exige instalar FFmpeg; reproducción o conversión serían funcionalidades posteriores con sus propios requisitos.

SQLite se utilizará mediante `sqlite3`, incluido en las distribuciones habituales de CPython. El diagnóstico verificará su disponibilidad y funcionamiento; no se exigirá instalar un servidor de base de datos ni el ejecutable `sqlite3`.

Se versionarán `pyproject.toml`, `.python-version` y `uv.lock`. El lock contendrá versiones concretas y hashes de dependencias, incluyendo variantes de plataforma. Las dependencias de construcción se fijarán también en su configuración. Cada PC generará su propia `.venv`; nunca se trasladará como parte del proyecto. Véanse [estructura de proyectos uv](https://docs.astral.sh/uv/concepts/projects/layout/) y [portabilidad de los entornos Python](https://docs.python.org/3/library/venv.html).

Se configurará `python-preference = "only-managed"` y se usarán `required-environments` para las arquitecturas comprometidas. Esta última opción ayuda a detectar ausencia de wheels en paquetes sin distribución de fuentes; las comprobaciones reales de instalación seguirán siendo necesarias. [Configuración de uv](https://docs.astral.sh/uv/reference/settings/).

Durante la preparación inicial se generará `uv.lock`. Después, la instalación habitual usará `uv sync --locked`: un desacuerdo entre el manifiesto y el lock provocará un error. Las actualizaciones se harán explícitamente y se revisarán junto con ambos archivos. `--frozen` omite la comprobación de coherencia y no será el comando habitual de incorporación al proyecto. [Sincronización de uv](https://docs.astral.sh/uv/concepts/projects/sync/).

## 5. Instalación de requisitos ausentes

En este PC ya están presentes las herramientas iniciales. Falta crear el entorno del proyecto, instalar su Python administrado y verificar sus dependencias.

Para otro PC:

1. Instalar Git desde las [instrucciones oficiales para cada sistema](https://git-scm.com/install/). Comprobar `git --version`.
2. Instalar la versión fijada de `uv` con uno de los comandos siguientes. Reabrir la terminal si fuera necesario y comprobar `uv --version`.
3. Clonar el repositorio o copiar sus fuentes y ejecutar `uv python install` desde la raíz. El comando leerá `.python-version`; no hace falta que el Python global coincida con el del proyecto. [Instalación de Python con uv](https://docs.astral.sh/uv/guides/install-python/).
4. Para trabajar en VS Code, instalarlo desde su [descarga oficial](https://code.visualstudio.com/download) y aceptar las extensiones recomendadas del workspace. El editor será opcional para ejecutar Trackfolio.
5. Para gestionar GitHub desde terminal, instalar opcionalmente [GitHub CLI](https://github.com/cli/cli#installation) y ejecutar `gh auth login`. GitHub CLI no será una dependencia de la aplicación.

Linux/macOS, instalación de `uv`:

```sh
curl -LsSf https://astral.sh/uv/0.12.10/install.sh | sh
```

Windows, instalación de `uv` desde PowerShell:

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/0.12.10/install.ps1 | iex"
```

Son los mecanismos oficiales para [instalar una versión específica de uv](https://docs.astral.sh/uv/getting-started/installation/). No se instalarán paquetes del proyecto globalmente con `pip`.

Los wheels de PySide6 incluyen Qt, por lo que no se exigirá instalar el SDK Qt completo. [Instalación de Qt for Python](https://doc.qt.io/qtforpython-6/gettingstarted.html). En GNU/Linux pueden faltar bibliotecas gráficas del sistema: `uv` no instala esos paquetes. El diagnóstico identificará el fallo y `docs/environment.md` relacionará la biblioteca ausente con su paquete y comando de instalación por distribución, siguiendo los [requisitos de Qt 6.11 para Linux](https://doc.qt.io/qt-6.11/linux-requirements.html).

Ejemplo concreto: si falta `libxcb-cursor.so.0`, Ubuntu/Debian necesitan `sudo apt install libxcb-cursor0`; Arch y derivados, `sudo pacman -S --needed xcb-util-cursor`. Se documentarán también las dependencias del backend elegido que aparezcan en las pruebas. Estos comandos resuelven esa biblioteca concreta; la GUI se volverá a comprobar después. Referencias: [paquete Ubuntu](https://packages.ubuntu.com/noble/libxcb-cursor0), [archivos del paquete Arch](https://archlinux.org/packages/extra/x86_64/xcb-util-cursor/files/).

## 6. Preparación y diagnóstico antes de desarrollar

Se crearán dos herramientas portables, escritas en Python:

- `bootstrap.py`: comprueba `uv` y su versión, instala el Python fijado y sincroniza desde el lock. Admitirá preparación del núcleo o de la GUI. Será repetible y propagará los errores. Las llamadas externas usarán argumentos estructurados, sin depender de Bash, Make ni `shell=True`.
- `doctor.py`: comprueba intérprete, SO, arquitectura, versiones instaladas, imports, operación SQLite temporal, recursos y requisitos específicos de GUI. Mostrará errores accionables y devolverá un código distinto de cero cuando falte un requisito obligatorio.

El diagnóstico de Qt se ejecutará en un subproceso, porque un fallo del plugin gráfico puede abortar el proceso. Distinguirá una prueba sin pantalla (`offscreen`) de una prueba en el escritorio real; la primera no demuestra que X11, Wayland o el backend nativo funcionen.

Una vez creados el manifiesto, el lock y los scripts, los comandos comunes a las tres plataformas serán:

```sh
uv python install
uv sync --locked --extra gui --group dev
uv run --locked --extra gui python scripts/doctor.py --gui
code Trackfolio.code-workspace
```

Para desarrollar el núcleo sin Qt:

```sh
uv python install
uv sync --locked --group dev
uv run --locked python scripts/doctor.py --core
```

Estos comandos son parte del entorno previsto y todavía no se pueden ejecutar contra este directorio: los archivos necesarios se crearán al realizar el plan. Se mantendrá explícito el extra `gui` en las tareas que lo necesiten. Los extras son opcionales y el grupo `dev` contiene herramientas de desarrollo, según la [gestión de dependencias de uv](https://docs.astral.sh/uv/concepts/projects/dependencies/).

## 7. Git y preparación para GitHub

Se inicializará Git después de generar los archivos de infraestructura:

```sh
git init -b main
git config --local core.autocrlf false
git config --local pull.ff only
git config --get user.name
git config --get user.email
```

Se conservará la identidad ya configurada. En un equipo donde falte, se configurarán el nombre y el correo que el desarrollador use para sus commits, mediante `git config --local user.name` y `git config --local user.email`. Estas opciones no se incluirán en los archivos compartidos. [Configuración de Git](https://git-scm.com/book/en/v2/Getting-Started-First-Time-Git-Setup).

Se revisarán los archivos a incluir y se hará un primer commit exclusivamente con el entorno y la documentación. Para crear posteriormente el remoto, la propuesta inicial es un repositorio privado:

```sh
gh repo create Evilchuck666/Trackfolio --private --source=. --remote=origin
git push -u origin main
```

La visibilidad es una propuesta del plan; se podrá elegir pública al ejecutarlo. Antes de crear el remoto se volverá a comprobar si ya existe. Si existe, se configurará su URL como `origin` y se revisará su historial antes de subir commits. Las credenciales se gestionarán mediante GitHub CLI o el gestor de credenciales de Git; no se escribirán en el proyecto. [Creación de repositorios con GitHub CLI](https://cli.github.com/manual/gh_repo_create).

## 8. Workspace de VS Code

Se ampliará el workspace existente, conservando `folders: [{"path": "."}]`:

- Detectar el entorno local `.venv`, con selección explícita desde «Python: Select Interpreter» si hay una preferencia local distinta. No fijar `/home/...`, `.venv/bin/python` ni rutas que fallen en Windows.
- Recomendar Python, Pylance, Python Debugger y Ruff. Formato y análisis se configurarán en `pyproject.toml`, compartidos por terminal y editor.
- Añadir tareas de tipo `process` con ejecutable `uv` y argumentos separados para preparar, diagnosticar, comprobar formato y ejecutar pruebas cuando existan. El directorio de trabajo será `${workspaceFolder}`.
- Posponer la configuración de lanzamiento de la aplicación hasta que exista su punto de entrada.

El editor admite descubrimiento de `.venv`; las preferencias explícitas del usuario pueden prevalecer sobre los valores por defecto. [Entornos Python en VS Code](https://code.visualstudio.com/docs/python/environments).

## 9. Arquitectura que debe preservar el entorno

La dependencia será: interfaces → casos de uso → dominio. Los adaptadores de infraestructura implementarán los contratos definidos hacia el interior; el punto de arranque conectará las piezas.

`domain` contendrá entidades y reglas; `application`, casos de uso y contratos; `infrastructure`, persistencia SQLAlchemy y acceso a metadatos/archivos; `interfaces/gui`, presentación y traducción de eventos. El dominio y los casos de uso no importarán Qt ni expondrán widgets, señales, `QObject` o modelos ORM como su contrato público.

La GUI solicitará operaciones y mostrará resultados. Una futura CLI/TUI o API utilizará los mismos casos de uso. Un servidor futuro accederá a los archivos musicales y a SQLite en su propia máquina; el frontend remoto consumirá la API. Se reservará esta posibilidad sin desarrollar esas interfaces durante la preparación.

La política de rutas utilizará `pathlib`, identificadores de biblioteca y rutas relativas a su raíz para las pistas. La raíz de la música podrá cambiar por equipo. Configuración y BD estarán en directorios de usuario adecuados al sistema; los recursos visuales se empaquetarán con la aplicación.

## 10. Apariencia uniforme prevista

Se propone Qt Widgets con estilo **Fusion** explícito, paleta y estilos propios, y fuentes e iconos incluidos como recursos. Para conservar la apariencia de los diálogos se elegirán implementaciones Qt en las superficies que deban ser uniformes. [Estilos de Qt](https://doc.qt.io/qt-6/qstylefactory.html).

El criterio visual será el mismo diseño del área de aplicación: controles, colores, tipografía, iconos y distribución. Los sistemas pueden producir diferencias de rasterizado y escalado DPI. Si «idéntica» incluye también el marco y la barra de título, habrá que implementar decoraciones propias y validar sus comportamientos de ventana y accesibilidad; Fusion por sí solo no cubre esa exigencia.

## 11. Validación y criterio de finalización

Se preparará GitHub Actions para recrear el entorno desde cero en Windows x86-64, Linux x86-64 y macOS Intel/ARM, usando el Python y `uv` fijados. Las acciones se fijarán por revisión y las imágenes de ejecución se elegirán explícitamente entre las disponibles. La configuración seguirá la [integración oficial de uv con GitHub Actions](https://docs.astral.sh/uv/guides/integration/github/).

Antes de empezar la aplicación deberán cumplirse estas condiciones:

1. El repositorio contiene manifiesto, lock, versión de Python, documentación y workspace portable.
2. Una copia o clon limpio, sin `.venv`, instala todas las dependencias desde el lock en la matriz objetivo.
3. Repetir la preparación mantiene el lock y las versiones previstas; un lock desactualizado provoca un error claro.
4. El diagnóstico comprueba SQLite y las dependencias usando el Python del proyecto.
5. La preparación del núcleo funciona sin instalar PySide6 y sin necesitar escritorio.
6. Qt abre una ventana mínima y procesa eventos en los escritorios probados. Linux incluye comprobaciones de X11 y Wayland; las pruebas sin pantalla se registran por separado.
7. VS Code selecciona el entorno local y las tareas funcionan sin rutas personales ni dependencia de un shell concreto.
8. Los fallos de requisitos producen instrucciones de instalación específicas y códigos de salida útiles.

Los resultados se registrarán por SO y arquitectura. Este documento no afirma que Windows y macOS ya hayan pasado las comprobaciones: para garantizar la portabilidad habrá que ejecutar esa matriz.

Orden de ejecución: archivos del proyecto → manifiesto y lock → preparación/diagnóstico → workspace → Git y remoto → validación multiplataforma. El desarrollo de Trackfolio comenzará cuando esta infraestructura quede comprobada.
