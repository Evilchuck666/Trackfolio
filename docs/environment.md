# Entorno portable de desarrollo

Trackfolio reconstruye su entorno en cada PC a partir de archivos versionados. La primera preparación necesita acceso a Internet para descargar el intérprete y los paquetes. Las bibliotecas gráficas del sistema se comprueban aparte: un entorno Python no puede sustituirlas.

## Versiones y archivos que se comparten

| Elemento | Contrato del proyecto |
| --- | --- |
| uv | 0.12.10, exigido por `tool.uv.required-version` |
| CPython | 3.13.15 en `.python-version`, administrado por uv |
| Versiones Python admitidas | `>=3.13,<3.14` en el manifiesto; el entorno de desarrollo usa el parche fijado |
| Backend de construcción | `uv_build==0.12.10` |
| Núcleo | SQLAlchemy, Alembic, Mutagen y platformdirs |
| Extra `gui` | `PySide6==6.11.2` |
| Grupo `dev` | pytest, Ruff y mypy |
| Dependencias resueltas | Versiones y hashes en `uv.lock` |

`python-preference = "only-managed"` impide elegir el Python global como sustituto del intérprete del proyecto. `required-environments` exige disponibilidad de dependencias para las arquitecturas objetivo durante la resolución; la ejecución todavía requiere comprobar cada sistema. [Configuración de uv](https://docs.astral.sh/uv/reference/settings/).

Se versionan `.python-version`, `pyproject.toml` y `uv.lock`. `.venv` contiene ejecutables y rutas propios del PC: se crea localmente, se excluye de Git y se reconstruye tras una migración. [Portabilidad de entornos Python](https://docs.python.org/3/library/venv.html).

SQLite se usa a través del módulo `sqlite3` de CPython. El diagnóstico verifica una operación real; no necesitas instalar un servidor de BD ni el comando `sqlite3`. PySide6 incluye Qt en sus wheels; no necesitas un SDK Qt independiente. [Instalación de Qt for Python](https://doc.qt.io/qtforpython-6/gettingstarted.html).

## Instalar las herramientas iniciales

1. Instala Git desde las [instrucciones oficiales](https://git-scm.com/install/) y comprueba `git --version`.
2. Instala **uv 0.12.10** con el comando de tu plataforma y comprueba `uv --version` después de abrir una terminal nueva.
3. Si vas a usar VS Code, descárgalo desde [su web oficial](https://code.visualstudio.com/download). Es opcional para ejecutar los comandos de desarrollo.
4. Para autenticarte y gestionar GitHub desde terminal, puedes instalar [GitHub CLI](https://github.com/cli/cli#installation), ejecutar `gh auth login` y configurar Git mediante `gh auth setup-git`. También puedes usar tu gestor de credenciales habitual.

Linux y macOS:

```sh
curl -LsSf https://astral.sh/uv/0.12.10/install.sh | sh
```

Windows, desde PowerShell:

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/0.12.10/install.ps1 | iex"
```

Estos instaladores permiten fijar la versión en la URL. Si ya tienes otro uv, instala la versión requerida y comprueba qué ejecutable encuentra tu terminal. No actualices uv automáticamente para este proyecto. [Instalación oficial de uv](https://docs.astral.sh/uv/getting-started/installation/).

No necesitas instalar globalmente CPython 3.13.15. uv descarga su distribución administrada y la mantiene separada del Python del sistema. Desde la raíz, la instalación explícita es:

```sh
uv python install 3.13.15
```

El comando de preparación siguiente también realiza ese paso. [Instalación de Python con uv](https://docs.astral.sh/uv/guides/install-python/).

## Preparar y diagnosticar

Todos los comandos de esta sección se ejecutan desde la raíz de Trackfolio y funcionan sin activar `.venv`.

Para desarrollar la GUI:

```sh
uv run --no-project --python 3.13.15 python scripts/bootstrap.py --gui
```

`bootstrap.py` verifica uv y los archivos de entorno, instala el Python fijado, ejecuta `uv sync --locked --extra gui --group dev` y llama al diagnóstico. El lanzador usa `--no-project` para iniciar la preparación antes de sincronizar las dependencias del paquete. El script devuelve el fallo de un paso obligatorio y puede repetirse.

Para desarrollar el núcleo sin instalar Qt:

```sh
uv run --no-project --python 3.13.15 python scripts/bootstrap.py --core
```

Puedes repetir la sincronización y el diagnóstico por separado:

```sh
uv sync --locked --extra gui --group dev
uv run --locked --extra gui python scripts/doctor.py --gui
```

El diagnóstico comprueba el intérprete, SO/arquitectura, imports, versiones de dependencias, SQLite y recursos del paquete; la preparación comprueba además uv. Con `--gui` comprueba también los requisitos gráficos y abre una ventana mínima en un subproceso, para que un plugin de Qt que aborte no derribe el diagnóstico principal. `--qt-timeout` permite cambiar su límite de espera en segundos, cuyo valor predeterminado es 15.

En Linux puedes elegir el backend de escritorio:

```sh
uv run --locked --extra gui python scripts/doctor.py --gui --platform xcb
uv run --locked --extra gui python scripts/doctor.py --gui --platform wayland
```

El backend X11 necesita una sesión accesible mediante `DISPLAY`; Wayland necesita el compositor y su conexión de sesión. Ejecuta esas comprobaciones desde una terminal del escritorio correspondiente. Para una máquina sin pantalla:

```sh
uv run --locked --extra gui python scripts/doctor.py --gui --platform offscreen
```

`offscreen` comprueba Qt sin un escritorio. No valida X11, Wayland, interacción de ventanas ni apariencia. También puede seleccionarse durante la preparación mediante `bootstrap.py --gui --platform offscreen`.

Las alternativas del núcleo son:

```sh
uv sync --locked --group dev
uv run --locked python scripts/doctor.py --core
```

Los extras son explícitos. Un comando que sincronice sin `--extra gui` puede retirar PySide6 del entorno; añade ese extra en los comandos que necesitan Qt. `--locked` falla si el manifiesto y el lock no concuerdan. `--frozen` no realiza esa comprobación y no se usa para la preparación habitual. [Sincronización de proyectos uv](https://docs.astral.sh/uv/concepts/projects/sync/).

## Requisitos de la GUI por sistema

| Sistema | Matriz inicial |
| --- | --- |
| Windows | Windows 10 1809+ / Windows 11, x86-64 |
| macOS | macOS 13+, Intel x86-64 y Apple Silicon ARM64 |
| GNU/Linux | x86-64 con glibc 2.34+ y bibliotecas del backend gráfico elegido |

La matriz combina los [requisitos de Qt](https://doc.qt.io/qtforpython-6/overviews/qtdoc-supported-platforms.html) con los [wheels de PySide6 6.11.2](https://pypi.org/project/PySide6/6.11.2/). No incluye Alpine/musl, Linux ARM64 ni Windows ARM64. Los resultados medidos se registran en [VALIDATION.md](../VALIDATION.md); esta tabla no afirma que todas las combinaciones hayan sido comprobadas.

### Bibliotecas gráficas ausentes en GNU/Linux

uv instala paquetes Python y Qt, pero las dependencias nativas del backend siguen perteneciendo a la distribución. Qt documenta las bibliotecas necesarias para X11 en [sus requisitos Linux](https://doc.qt.io/qt-6.11/linux-requirements.html). Instala el paquete que corresponda al error detectado y repite el diagnóstico.

| Error o biblioteca ausente | Ubuntu | Arch Linux |
| --- | --- | --- |
| `libxcb-cursor.so.0` | `libxcb-cursor0` | `xcb-util-cursor` |
| `libxkbcommon-x11.so.0` | `libxkbcommon-x11-0` | `libxkbcommon-x11` |

Referencias de los paquetes: [cursor en Ubuntu](https://packages.ubuntu.com/noble/libxcb-cursor0), [xkbcommon X11 en Ubuntu](https://packages.ubuntu.com/noble/libxkbcommon-x11-0), [archivos de cursor en Arch](https://archlinux.org/packages/extra/x86_64/xcb-util-cursor/files/) y [archivos de xkbcommon X11 en Arch](https://archlinux.org/packages/extra/x86_64/libxkbcommon-x11/files/).

Por ejemplo, para resolver esas dos bibliotecas en Ubuntu:

```sh
sudo apt update
sudo apt install libxcb-cursor0 libxkbcommon-x11-0
```

En Arch, usando un sistema actualizado:

```sh
sudo pacman -S --needed xcb-util-cursor libxkbcommon-x11
```

Estos paquetes resuelven esas bibliotecas concretas; no garantizan que todo escritorio mínimo tenga el resto. El diagnóstico identifica otros fallos y ofrece orientación para el SO. No cambies las rutas de plugins para cargar una instalación Qt diferente. Si la glibc es demasiado antigua o la arquitectura no tiene un wheel admitido, usa un sistema dentro de la matriz en lugar de modificar el lock para ese PC.

## Migrar a otro PC

Sube los cambios de fuentes y configuración a Git. En el equipo nuevo instala Git y uv 0.12.10, autentícate si el repositorio sigue privado y ejecuta:

```sh
git clone https://github.com/Evilchuck666/Trackfolio.git
cd Trackfolio
uv run --no-project --python 3.13.15 python scripts/bootstrap.py --gui
code Trackfolio.code-workspace
```

Puedes usar otra ruta de destino. Si transfieres las fuentes sin Git, incluye los archivos ocultos de configuración y el lock, y excluye `.venv`, caches, credenciales, música y bases de datos. Reconstruye el entorno en destino. Conserva y transfiere los datos de usuario por separado cuando la aplicación implemente su almacenamiento.

El workspace usa una carpeta relativa y tareas de tipo `process` con argumentos separados. Si VS Code recuerda un intérprete ajeno, selecciona `.venv` mediante **Python: Select Interpreter**. [Entornos Python en VS Code](https://code.visualstudio.com/docs/python/environments).

## Resolver fallos habituales

| Fallo | Acción |
| --- | --- |
| No se encuentra `uv`, `git` o `code` | Instala la herramienta correspondiente y reabre la terminal; `code` es opcional |
| Versión de uv distinta de 0.12.10 | Usa el instalador fijado y comprueba el ejecutable encontrado en `PATH` |
| Descarga de Python o paquetes fallida | Comprueba conexión, proxy y certificados de tu red; repite la preparación |
| Lock desactualizado | Trae los archivos de una misma revisión de Git; para un cambio deliberado actualiza el lock siguiendo `CONTRIBUTING.md` |
| Entorno copiado o intérprete incorrecto | Elimina únicamente la `.venv` local del proyecto y vuelve a prepararlo |
| Falta una dependencia Python | Ejecuta la sincronización del núcleo o con `--extra gui`, según el diagnóstico |
| Qt no conecta con X11 o Wayland | Usa una terminal de la sesión de escritorio, comprueba el backend y las bibliotecas que informa el diagnóstico |
| `offscreen` pasa pero el escritorio falla | Resuelve el backend de escritorio; la prueba sin pantalla no lo valida |

## Validación continua

GitHub Actions recrea el entorno en Windows x86-64, GNU/Linux x86-64 y macOS Intel/ARM. Sus pruebas diferencian núcleo, Qt sin pantalla y backend de escritorio. Las comprobaciones automáticas no sustituyen las pruebas manuales de apariencia y comportamiento de ventanas en las plataformas objetivo. Consulta los resultados concretos y las limitaciones en [VALIDATION.md](../VALIDATION.md).
