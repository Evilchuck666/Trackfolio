# Portable development environment

Trackfolio rebuilds its environment on each PC from versioned files. Initial setup needs Internet access to download the interpreter and packages. System graphical libraries are checked separately: a Python environment cannot replace them.

## Versions and shared files

| Item | Project contract |
| --- | --- |
| uv | `>=0.13.4,<0.14`, enforced by `tool.uv.required-version` |
| CPython | 3.13.15 in `.python-version`, managed by uv |
| Supported Python versions | `>=3.13,<3.14` in the manifest; development uses the pinned patch |
| Build backend | `uv_build==0.12.10` |
| Core | SQLAlchemy, Alembic, Mutagen and platformdirs |
| `gui` extra | `PySide6==6.11.2` |
| `dev` group | pytest, Ruff and mypy |
| Resolved dependencies | Versions and hashes in `uv.lock` |

`python-preference = "only-managed"` prevents using global Python as a substitute for the project interpreter. `required-environments` requires dependency availability for target architectures during resolution; execution still needs verification on each system. [uv settings](https://docs.astral.sh/uv/reference/settings/).

`.python-version`, `pyproject.toml` and `uv.lock` are versioned. `.venv` contains machine-specific executables and paths: it is created locally, excluded from Git and rebuilt after migration. [Python environment portability](https://docs.python.org/3/library/venv.html).

SQLite is accessed through CPython's `sqlite3` module. Diagnostics verify a real operation; you do not need a database server or the `sqlite3` command. PySide6 includes Qt in its wheels; no separate Qt SDK is needed. [Qt for Python installation](https://doc.qt.io/qtforpython-6/gettingstarted.html).

## Install initial tools

The recommended route is to run the launcher after downloading the repository; these manual steps remain available as an alternative.

1. Install Git using the [official instructions](https://git-scm.com/install/) and check `git --version`.
2. Install **uv >=0.13.4 and <0.14** and check `uv --version` after opening a new terminal. An existing compatible version, such as 0.13.4, can be kept. The following commands install 0.13.4, the minimum supported version.
3. If using VS Code, download it from [its official website](https://code.visualstudio.com/download). It is optional for development commands.
4. To authenticate and manage GitHub from a terminal, optionally install [GitHub CLI](https://github.com/cli/cli#installation), run `gh auth login` and configure Git with `gh auth setup-git`. Your usual credential manager also works.

Linux and macOS:

```sh
curl -LsSf https://astral.sh/uv/0.13.4/install.sh | sh
```

Windows, from PowerShell:

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/0.13.4/install.ps1 | iex"
```

These installers accept a specific version in the URL. You do not need to downgrade to 0.13.4 if installed uv is within `>=0.13.4,<0.14`. Otherwise, install a compatible version and check which executable your terminal finds. When system and user installations coexist, `PATH` order determines which is used; restart the editor if it retains an earlier environment. Using uv 0.14 or later requires widening and validating the project contract. [Official uv installation](https://docs.astral.sh/uv/getting-started/installation/).

The uv executable requirement is independent of `uv_build==0.12.10`: the build backend remains pinned for reproducible packaging. Python, PySide6 and `uv.lock` dependency versions also remain unchanged when using another compatible uv patch.

## Single-command setup

Download the repository's `gui` branch from GitHub using Git or a ZIP, and enter its root:

```sh
# Linux and macOS; no prior Python or uv installation required.
bash setup.sh
```

```powershell
# Windows PowerShell 5.1 or later.
powershell -NoProfile -ExecutionPolicy Bypass -File .\setup.ps1
```

Both launchers read the minimum uv version from `pyproject.toml` and the interpreter from `.python-version`. They first select a compatible uv in `PATH`, then the copy in `.tools/uv`. uv checks the project requirement without downloading Python during selection. If neither works, they download the official minimum-version installer through HTTPS and run it with `UV_UNMANAGED_INSTALL` and `UV_NO_MODIFY_PATH`: this uv installation does not write to `~/.local/bin`, edit profiles or enable automatic updates. Managed Python is required even to start setup, through `--managed-python`. Dependencies and diagnostics are delegated to `scripts/bootstrap.py`.

Linux and macOS need Bash and basic system utilities. If curl and wget are both missing, the launcher offers to install curl through apt-get, pacman or dnf with confirmation and administrator privileges. macOS includes curl. Windows uses PowerShell and `Invoke-WebRequest`; it needs neither Git Bash nor system Python.

| Argument | Behavior |
| --- | --- |
| No arguments / `--gui` | Python, `.venv`, GUI, development tools, diagnostics and setup of an available editor |
| `--core` | Core and development tools without installing Qt |
| `--skip-editor` | Do not download VS Code or install extensions; Git remains optional |
| `--platform xcb` / `wayland` / `offscreen` | Select the GUI diagnostic backend |
| `--qt-timeout SECONDS` | Qt diagnostic timeout, between 0 and 300 seconds |
| `--non-interactive` | Do not prompt; reject proposed installations unless `--yes` is supplied |
| `--yes` | Explicitly authorize proposed installations, even without an interactive terminal |
| `--open-code` | Open the workspace when finished; incompatible with `--skip-editor` |
| `--run-uv COMMAND ...` | Only select uv and run the command; do not download tools or repeat setup |
| `--help` | Show help without downloading or setting up anything |

On Linux without a desktop session, diagnostics select `offscreen` and report that limitation. With a session, they select X11 or Wayland. Required libraries are compared with available ones; when missing, commands are shown before requesting installation permission. Automatic library installation supports Debian/Ubuntu (apt-get), Arch/Artix (pacman) and Fedora/derivatives (dnf). Other distributions receive library names for manual installation. The complete system is not upgraded and package repositories are not changed.

Git is reused when available. If missing, installation is offered through those package managers, an existing Homebrew on macOS, or an existing winget on Windows. Without a supported manager, or if declined, a warning is shown: Git is not required to run the app. The script does not install Homebrew, configure credentials or accept licenses on its own; accepting the proposal or using `--yes` authorizes the displayed command, including its installation agreements.

Do not run the entire setup with `sudo`: only package-manager commands elevate privileges when necessary. Even with `--yes`, sudo may request a password; script authorization does not replace system permissions.

VS Code is also reused, including installations in standard Windows/macOS locations. If absent and approved, the official Microsoft stable distribution is downloaded into `.tools/vscode`; space is needed for download and extraction. This installation creates no file associations or system shortcuts. Open it with `--open-code`. Extensions are read from `.vscode/extensions.json`; the local interpreter is specified in `Trackfolio.code-workspace`. A failed editor download or installation returns an error. An extension that cannot be installed produces a warning without invalidating the Python environment: variants such as Code OSS use another marketplace and may not offer Pylance. Retry the extension or use official VS Code. `--skip-editor` skips editor and extension setup. An unrecognized editor folder is not overwritten.

VS Code tasks run through `setup.sh` or `setup.ps1`, and integrated terminals add `.tools/uv` to that terminal's `PATH`. Development therefore does not require globally installing the downloaded uv. Outside the editor, use:

```sh
bash setup.sh --run-uv run --locked --extra gui trackfolio
bash setup.sh --run-uv run --locked --extra gui pytest
```

On Windows, replace `bash setup.sh` with `powershell -NoProfile -ExecutionPolicy Bypass -File .\setup.ps1`. `--run-uv` preserves command arguments and exit code. If compatible uv is already in `PATH`, direct commands in other sections still work.

Setup is repeatable: uv, Python, locked packages and the available editor are reused. `.tools` and `.venv` are excluded from Git and must be rebuilt on each machine. `uv.lock` is not modified, nothing is installed into global Python, and music and databases are untouched. To browse songs, open an existing catalog or import music separately. If the editor retains another interpreter, select `.venv` with **Python: Select Interpreter**.

You do not need to install CPython 3.13.15 globally. uv downloads its managed distribution and keeps it separate from system Python. From the root, explicit installation is:

```sh
uv python install 3.13.15
```

The setup command below also performs this step. [Installing Python with uv](https://docs.astral.sh/uv/guides/install-python/).

## Setup and diagnostics

All commands in this section run from the Trackfolio root without activating `.venv`.

For GUI development:

```sh
uv run --no-project --python 3.13.15 python scripts/bootstrap.py --gui
```

`bootstrap.py` verifies uv is within the configured range, checks environment files, installs pinned Python, runs `uv sync --locked --extra gui --group dev` and invokes diagnostics. It rejects versions below the minimum or at/above the maximum before installation and synchronization. The launcher uses `--no-project` to start preparation before synchronizing package dependencies. The script returns mandatory-step failures and is repeatable.

For core development without Qt:

```sh
uv run --no-project --python 3.13.15 python scripts/bootstrap.py --core
```

Synchronization and diagnostics can be repeated separately:

```sh
uv sync --locked --extra gui --group dev
uv run --locked --extra gui python scripts/doctor.py --gui
```

Diagnostics check the interpreter, OS/architecture, imports, dependency versions, SQLite and hashes of packaged fonts, license, icons and styles; setup also checks uv. With `--gui`, graphical requirements are verified and the product window opens with temporary data in a subprocess. Selection, metadata and artwork are checked without real music, isolating possible Qt plugin aborts from the main diagnostic. `--qt-timeout` changes the default 15-second timeout.

On Linux, select the desktop backend:

```sh
uv run --locked --extra gui python scripts/doctor.py --gui --platform xcb
uv run --locked --extra gui python scripts/doctor.py --gui --platform wayland
```

X11 needs a session accessible through `DISPLAY`; Wayland needs its compositor and session connection. Run these checks from a terminal in the corresponding desktop. For a headless machine:

```sh
uv run --locked --extra gui python scripts/doctor.py --gui --platform offscreen
```

`offscreen` checks Qt without a desktop. It does not validate X11, Wayland, window interaction or appearance. It can also be selected during setup with `bootstrap.py --gui --platform offscreen`.

Core alternatives:

```sh
uv sync --locked --group dev
uv run --locked python scripts/doctor.py --core
```

Extras are explicit. Synchronizing without `--extra gui` may remove PySide6; include that extra in commands needing Qt. `--locked` fails when manifest and lockfile disagree. `--frozen` does not check this and is not used for normal setup. [uv project synchronization](https://docs.astral.sh/uv/concepts/projects/sync/).

## GUI requirements by system

| System | Initial matrix |
| --- | --- |
| Windows | Windows 10 1809+ / Windows 11, x86-64 |
| macOS | macOS 13+, Intel x86-64 and Apple Silicon ARM64 |
| GNU/Linux | x86-64 with glibc 2.34+ and libraries for the chosen graphical backend |

The matrix combines [Qt requirements](https://doc.qt.io/qtforpython-6/overviews/qtdoc-supported-platforms.html) with [PySide6 6.11.2 wheels](https://pypi.org/project/PySide6/6.11.2/). It excludes Alpine/musl, Linux ARM64 and Windows ARM64. Measured results are recorded in [VALIDATION.md](../VALIDATION.md); this table does not claim every combination has been checked.

This matrix is for Trackfolio, not the editor: stable VS Code has [its own system requirements](https://code.visualstudio.com/docs/supporting/requirements). Minimal Linux desktops may also need Electron libraries to launch it.

### Missing graphical libraries on GNU/Linux

uv installs Python and Qt packages, but native backend dependencies still belong to the distribution. Qt documents required X11 libraries in [Linux requirements](https://doc.qt.io/qt-6.11/linux-requirements.html). Install the package matching the reported error and repeat diagnostics.

| Missing library or error | Ubuntu | Arch Linux |
| --- | --- | --- |
| `libxcb-cursor.so.0` | `libxcb-cursor0` | `xcb-util-cursor` |
| `libxkbcommon-x11.so.0` | `libxkbcommon-x11-0` | `libxkbcommon-x11` |

Package references: [Ubuntu cursor](https://packages.ubuntu.com/noble/libxcb-cursor0), [Ubuntu xkbcommon X11](https://packages.ubuntu.com/noble/libxkbcommon-x11-0), [Arch cursor files](https://archlinux.org/packages/extra/x86_64/xcb-util-cursor/files/) and [Arch xkbcommon X11 files](https://archlinux.org/packages/extra/x86_64/libxkbcommon-x11/files/).

For example, to resolve those two libraries on Ubuntu:

```sh
sudo apt update
sudo apt install libxcb-cursor0 libxkbcommon-x11-0
```

On Arch, using an up-to-date system:

```sh
sudo pacman -S --needed xcb-util-cursor libxkbcommon-x11
```

These packages resolve those specific libraries; they do not guarantee every minimal desktop has all the others. Diagnostics identify other failures and provide OS-specific guidance. Do not change plugin paths to load a different Qt installation. If glibc is too old or the architecture has no supported wheel, use a system in the matrix instead of modifying the lockfile for that PC.

## Move to another PC

Upload source and configuration changes to Git. On the new machine, download the `gui` branch as a ZIP or clone it if Git and private repository access are available:

```sh
git clone --branch gui https://github.com/Evilchuck666/Trackfolio.git
cd Trackfolio
bash setup.sh --open-code
```

On Windows, use the PowerShell command with `--open-code`. A different destination path is fine. When transferring source without Git, include hidden configuration files and the lockfile, and exclude `.venv`, `.tools`, caches, credentials, music and databases. Rebuild the destination environment. Keep and transfer SQLite catalogs separately. The GUI can display them even if music paths refer to another PC; metadata and artwork are in the database. After setup, use the launcher with `--run-uv run --locked --extra gui trackfolio --database "path/to/catalog.tfo"`. The last-catalog preference is stored locally through `platformdirs`.

The workspace uses a relative folder and `process` tasks with separate arguments. If VS Code remembers another interpreter, select `.venv` through **Python: Select Interpreter**. [Python environments in VS Code](https://code.visualstudio.com/docs/python/environments).

## Troubleshooting

| Failure | Action |
| --- | --- |
| `uv`, `git` or `code` not found | Run the launcher; it can download uv locally and offers Git/VS Code setup. `--run-uv` and `--open-code` use local copies |
| uv outside `>=0.13.4,<0.14` | Run the launcher to use a compatible copy without replacing system uv; for direct commands, check which uv `PATH` finds |
| Python or package download failed | Check connectivity, proxy and network certificates; repeat setup |
| Outdated lockfile | Obtain files from the same Git revision; for deliberate changes update the lock following `CONTRIBUTING.md` |
| Copied environment or incorrect interpreter | Remove only the project's local `.venv` and set it up again |
| Missing Python dependency | Run core sync or use `--extra gui`, as diagnostics indicate |
| Qt cannot connect to X11 or Wayland | Use a desktop-session terminal and check the backend and libraries reported by diagnostics |
| `offscreen` passes but desktop fails | Fix the desktop backend; headless testing does not validate it |

## Continuous validation

GitHub Actions recreates the environment through the launchers on Windows x86-64, GNU/Linux x86-64 and macOS Intel/ARM using a single uv version, 0.13.4 (minimum supported and downloaded into `.tools/uv`): four combinations in total. Launchers still accept compatible global versions, although CI only tests 0.13.4. Windows also checks Windows PowerShell 5.1. Linux and Windows jobs add a copy without uv or Python in `PATH` to verify local download and repeat core setup. Tests distinguish core, headless Qt and desktop backends. Automated checks do not replace manual appearance and window-behavior tests on target platforms. See specific results and limitations in [VALIDATION.md](../VALIDATION.md).
