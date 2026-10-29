# Entorno portable de desarrollo

Trackfolio reconstruye su entorno en cada PC a partir de archivos versionados. La primera preparación necesita acceso a Internet para descargar el intérprete y los paquetes. Las bibliotecas gráficas del sistema se comprueban aparte: un entorno Python no puede sustituirlas.

## Versiones y archivos que se comparten

| Elemento | Contrato del proyecto |
| --- | --- |
| uv | `>=0.13.4,<0.14`, exigido por `tool.uv.required-version` |
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

La ruta recomendada es ejecutar el lanzador después de descargar el repositorio; los pasos manuales de esta sección siguen disponibles como alternativa.

1. Instala Git desde las [instrucciones oficiales](https://git-scm.com/install/) y comprueba `git --version`.
2. Instala **uv >=0.13.4 y <0.14** y comprueba `uv --version` después de abrir una terminal nueva. Si ya tienes una versión compatible, como 0.13.4, puedes conservarla. Los comandos siguientes instalan 0.13.4, la versión mínima admitida.
3. Si vas a usar VS Code, descárgalo desde [su web oficial](https://code.visualstudio.com/download). Es opcional para ejecutar los comandos de desarrollo.
4. Para autenticarte y gestionar GitHub desde terminal, puedes instalar [GitHub CLI](https://github.com/cli/cli#installation), ejecutar `gh auth login` y configurar Git mediante `gh auth setup-git`. También puedes usar tu gestor de credenciales habitual.

Linux y macOS:

```sh
curl -LsSf https://astral.sh/uv/0.13.4/install.sh | sh
```

Windows, desde PowerShell:

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/0.13.4/install.ps1 | iex"
```

Estos instaladores permiten elegir una versión concreta en la URL. No necesitas volver a 0.13.4 si el uv instalado está dentro de `>=0.13.4,<0.14`. Si está fuera del rango, instala una versión compatible y comprueba qué ejecutable encuentra tu terminal. Cuando coexistan una instalación de sistema y otra de usuario, el orden de `PATH` determina cuál se utiliza; reinicia el editor si conserva un entorno anterior. Antes de usar uv 0.14 o posterior hay que ampliar y validar el contrato del proyecto. [Instalación oficial de uv](https://docs.astral.sh/uv/getting-started/installation/).

El requisito del ejecutable uv es independiente de `uv_build==0.12.10`: el backend de construcción sigue fijado para mantener reproducible el empaquetado. Las versiones de Python, PySide6 y las dependencias de `uv.lock` tampoco cambian al usar otro parche compatible de uv.

## Preparación en un solo comando

Descarga la rama `gui` del repositorio de GitHub, mediante Git o un ZIP, y entra en su raíz:

```sh
# Linux y macOS; no hace falta instalar Python ni uv antes.
bash setup.sh
```

```powershell
# Windows PowerShell 5.1 o posterior.
powershell -NoProfile -ExecutionPolicy Bypass -File .\setup.ps1
```

Los dos lanzadores leen el mínimo de uv desde `pyproject.toml` y el intérprete desde `.python-version`. Seleccionan primero un uv compatible en `PATH` y después la copia de `.tools/uv`. uv comprueba el requisito del proyecto sin descargar Python durante esa selección. Si ninguna copia sirve, descargan el instalador oficial de la versión mínima mediante HTTPS, y lo ejecutan con `UV_UNMANAGED_INSTALL` y `UV_NO_MODIFY_PATH`: esa instalación de uv no escribe en `~/.local/bin`, no edita perfiles y no habilita actualizaciones automáticas. Incluso para iniciar la preparación, se exige Python administrado mediante `--managed-python`. Las dependencias y el diagnóstico se delegan en `scripts/bootstrap.py`.

Linux y macOS necesitan Bash y las utilidades básicas del sistema. Si no hay curl ni wget, el lanzador ofrece instalar curl con apt-get, pacman o dnf, con confirmación y permisos de administrador. macOS incluye curl. Windows utiliza PowerShell e `Invoke-WebRequest`; no necesita Git Bash ni Python del sistema.

| Argumento | Comportamiento |
| --- | --- |
| Sin argumentos / `--gui` | Python, `.venv`, GUI, herramientas de desarrollo, diagnóstico y preparación del editor disponible |
| `--core` | Núcleo y herramientas de desarrollo, sin instalar Qt |
| `--skip-editor` | No descarga VS Code ni instala extensiones; Git sigue siendo opcional |
| `--platform xcb` / `wayland` / `offscreen` | Selecciona el backend del diagnóstico GUI |
| `--qt-timeout SEGUNDOS` | Límite de espera del diagnóstico Qt, entre 0 y 300 segundos |
| `--non-interactive` | No realiza preguntas del script; rechaza las instalaciones propuestas salvo con `--yes` |
| `--yes` | Autoriza explícitamente las instalaciones propuestas, incluso sin terminal interactiva |
| `--open-code` | Abre el workspace al terminar; no se combina con `--skip-editor` |
| `--run-uv COMANDO ...` | Sólo selecciona uv y ejecuta el comando; no descarga herramientas ni repite la preparación |
| `--help` | Muestra ayuda sin descargar ni preparar nada |

En Linux, sin sesión de escritorio el diagnóstico elige `offscreen` e informa de esa limitación. Con sesión elige X11 o Wayland. Compara las bibliotecas necesarias con las disponibles y, si faltan, muestra los comandos antes de pedir permiso para instalarlas. La instalación automática de bibliotecas admite Debian/Ubuntu (apt-get), Arch/Artix (pacman) y Fedora/derivados (dnf). Otras distribuciones reciben los nombres de las bibliotecas que deben instalarse manualmente. No se actualiza el sistema completo ni se cambian repositorios de paquetes.

Git se reutiliza cuando está disponible. Si falta, se ofrece instalarlo con esos gestores, Homebrew ya instalado en macOS, o winget ya disponible en Windows. Sin gestor compatible, o si se rechaza, se avisa: Git no es necesario para ejecutar la app. El script no instala Homebrew, configura credenciales ni acepta licencias por su cuenta; aceptar la propuesta o usar `--yes` autoriza el comando mostrado, incluidos sus acuerdos de instalación.

No ejecutes toda la preparación con `sudo`: sólo los comandos del gestor de paquetes elevan permisos cuando hace falta. Incluso con `--yes`, sudo puede pedir la contraseña; la autorización del script no sustituye los permisos del sistema.

VS Code también se reutiliza, incluido el instalado en las ubicaciones habituales de Windows/macOS. Si falta y se acepta la propuesta, se descarga la distribución oficial estable de Microsoft en `.tools/vscode`; se necesita espacio para la descarga y extracción. Esta instalación no crea asociaciones de archivos ni accesos del sistema. Se abre con `--open-code`. Las extensiones se leen de `.vscode/extensions.json`; el intérprete local se indica en `Trackfolio.code-workspace`. Una descarga o instalación del editor fallida devuelve un error. Una extensión que no pueda instalarse genera un aviso, sin invalidar el entorno Python: algunas variantes como Code OSS utilizan otro catálogo y no ofrecen Pylance. Puedes reintentar la extensión o utilizar VS Code oficial. `--skip-editor` omite la preparación del editor y sus extensiones. No se sobrescribe una carpeta del editor que no se reconozca.

Las tareas de VS Code pasan por `setup.sh` o `setup.ps1`, y las terminales integradas añaden `.tools/uv` al `PATH` de esa terminal. Por tanto, puedes programar sin que el uv descargado esté instalado globalmente. Fuera del editor, también puedes usarlo así:

```sh
bash setup.sh --run-uv run --locked --extra gui trackfolio
bash setup.sh --run-uv run --locked --extra gui pytest
```

En Windows sustituye `bash setup.sh` por `powershell -NoProfile -ExecutionPolicy Bypass -File .\setup.ps1`. `--run-uv` conserva los argumentos y el código de salida del comando. Si ya tienes uv compatible en `PATH`, los comandos directos de las demás secciones siguen funcionando.

Puedes repetir la preparación: se reutilizan uv, Python, los paquetes del lock y el editor disponible. `.tools` y `.venv` están excluidas de Git; cada equipo debe reconstruirlas. No se modifica `uv.lock`, no se instala nada en el Python global y no se tocan música ni bases de datos. Para consultar canciones hay que abrir un catálogo existente o importar música por separado. Si el editor conserva otro intérprete, selecciona `.venv` con **Python: Select Interpreter**.

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

`bootstrap.py` verifica que uv esté dentro del rango configurado y comprueba los archivos de entorno, instala el Python fijado, ejecuta `uv sync --locked --extra gui --group dev` y llama al diagnóstico. Rechaza versiones inferiores al mínimo o iguales o superiores al máximo antes de ejecutar sus pasos de instalación y sincronización. El lanzador usa `--no-project` para iniciar la preparación antes de sincronizar las dependencias del paquete. El script devuelve el fallo de un paso obligatorio y puede repetirse.

Para desarrollar el núcleo sin instalar Qt:

```sh
uv run --no-project --python 3.13.15 python scripts/bootstrap.py --core
```

Puedes repetir la sincronización y el diagnóstico por separado:

```sh
uv sync --locked --extra gui --group dev
uv run --locked --extra gui python scripts/doctor.py --gui
```

El diagnóstico comprueba el intérprete, SO/arquitectura, imports, versiones de dependencias, SQLite y los hashes de fuentes, licencia, iconos y estilos empaquetados; la preparación comprueba además uv. Con `--gui` verifica los requisitos gráficos y abre la ventana del producto con datos temporales en un subproceso. Comprueba selección, metadatos y portada sin necesitar música real, y aísla un posible aborto del plugin Qt del diagnóstico principal. `--qt-timeout` permite cambiar su límite de espera, cuyo valor predeterminado es 15 segundos.

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

Esta matriz corresponde a Trackfolio, no al editor: VS Code estable tiene [sus propios requisitos de sistema](https://code.visualstudio.com/docs/supporting/requirements). Un escritorio Linux mínimo puede necesitar también bibliotecas de Electron para abrirlo.

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

Sube los cambios de fuentes y configuración a Git. En el equipo nuevo descarga la rama `gui` como ZIP o clónala si ya tienes Git y acceso al repositorio privado:

```sh
git clone --branch gui https://github.com/Evilchuck666/Trackfolio.git
cd Trackfolio
bash setup.sh --open-code
```

En Windows usa el comando PowerShell con `--open-code`. Puedes usar otra ruta de destino. Si transfieres las fuentes sin Git, incluye los archivos ocultos de configuración y el lock, y excluye `.venv`, `.tools`, caches, credenciales, música y bases de datos. Reconstruye el entorno en destino. Conserva y transfiere los catálogos SQLite por separado. La GUI puede mostrarlos aunque las rutas de la música correspondan a otro PC; los metadatos y las portadas están en la base. Después de preparar el entorno, usa el lanzador con `--run-uv run --locked --extra gui trackfolio --database "ruta/al/catalogo.tfo"`. La configuración del último catálogo abierto se guarda localmente mediante `platformdirs`.

El workspace usa una carpeta relativa y tareas de tipo `process` con argumentos separados. Si VS Code recuerda un intérprete ajeno, selecciona `.venv` mediante **Python: Select Interpreter**. [Entornos Python en VS Code](https://code.visualstudio.com/docs/python/environments).

## Resolver fallos habituales

| Fallo | Acción |
| --- | --- |
| No se encuentra `uv`, `git` o `code` | Ejecuta el lanzador; puede descargar uv localmente y propone preparar Git y VS Code. `--run-uv` y `--open-code` permiten usar las copias locales |
| Versión de uv fuera de `>=0.13.4,<0.14` | Ejecuta el lanzador para usar una copia compatible sin sustituir la instalación del sistema; con comandos directos, comprueba qué uv encuentra `PATH` |
| Descarga de Python o paquetes fallida | Comprueba conexión, proxy y certificados de tu red; repite la preparación |
| Lock desactualizado | Trae los archivos de una misma revisión de Git; para un cambio deliberado actualiza el lock siguiendo `CONTRIBUTING.md` |
| Entorno copiado o intérprete incorrecto | Elimina únicamente la `.venv` local del proyecto y vuelve a prepararlo |
| Falta una dependencia Python | Ejecuta la sincronización del núcleo o con `--extra gui`, según el diagnóstico |
| Qt no conecta con X11 o Wayland | Usa una terminal de la sesión de escritorio, comprueba el backend y las bibliotecas que informa el diagnóstico |
| `offscreen` pasa pero el escritorio falla | Resuelve el backend de escritorio; la prueba sin pantalla no lo valida |

## Validación continua

GitHub Actions recrea el entorno mediante los lanzadores en Windows x86-64, GNU/Linux x86-64 y macOS Intel/ARM con una única versión de uv, 0.13.4 (mínimo admitido y versión descargada en `.tools/uv`), cuatro combinaciones en total. Los lanzadores siguen admitiendo versiones globales compatibles, aunque CI sólo comprueba 0.13.4. Windows comprueba también Windows PowerShell 5.1. Los jobs de Linux y Windows añaden una copia sin uv ni Python en `PATH` para verificar la descarga local y repetir la preparación del núcleo. Sus pruebas diferencian núcleo, Qt sin pantalla y backend de escritorio. Las comprobaciones automáticas no sustituyen las pruebas manuales de apariencia y comportamiento de ventanas en las plataformas objetivo. Consulta los resultados concretos y las limitaciones en [VALIDATION.md](../VALIDATION.md).
