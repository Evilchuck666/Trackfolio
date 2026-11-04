# Trackfolio setup plan

Date: October 6, 2026. This document prepares the environment before application development.

> This is the original plan. Its infrastructure has been implemented; current commands are in README.md and measured results in VALIDATION.md. Section 1 describes the initial inspection.

This phase will deliver a repository that can be cloned onto another PC, opened in VS Code and prepared with the same `uv` commands. The music catalog, tag editor and CLI/TUI/web interfaces will not be implemented yet.

## 1. Verified situation

| Item | State on this PC |
| --- | --- |
| Directory | `/home/evilchuck/projects/Trackfolio` exists |
| Workspace | `Trackfolio.code-workspace` exists, with a relative `.` folder |
| Git | Installed: 2.55.0; the directory is not yet a repository |
| uv | Installed: 0.12.10 |
| System Python | CPython 3.14.7 |
| System SQLite | 3.53.4; in-memory query verified |
| VS Code | Installed: 1.140.0; Python, Pylance and debugging extensions available |
| GitHub CLI | Installed and authenticated as `Evilchuck666` over HTTPS |
| Git identity | Name and email configured; they will be reused |
| Remote repository | The query for `Evilchuck666/Trackfolio` found no accessible repository |

No dependencies have been installed, Git initialized or files published. The SQLite query checks the system Python; it must be repeated with the project interpreter. Qt's ability to open a window on this PC has not yet been checked either.

## 2. Compatibility contract

The promise is reproducibility on supported Windows, macOS and GNU/Linux systems. Having any Python 3 and `uv` version is not enough to run any Qt version.

Proposed baseline:

- CPython **3.13.15**, available for download according to the installed `uv`. Pin the patch in `.python-version`, use `uv`-managed Python and do not replace system Python. Verify installation on each target platform.
- `requires-python = ">=3.13,<3.14"` during the first stage. Expand support to other versions after they pass the verification matrix.
- `uv` **0.12.10**, the version checked on this PC. Enforce it through `tool.uv.required-version`; record tool changes in Git too.
- PySide6 **6.11.2** as an optional GUI dependency. SQLAlchemy, Mutagen and development tools will have versions resolved and recorded in `uv.lock` during setup.

The initial GUI target matrix is Windows 10 1809+/11 x86-64, macOS 13+ Intel and Apple Silicon, and GNU/Linux x86-64 with glibc 2.34+ and a compatible X11 or Wayland desktop. Published wheels do not prove functionality: these combinations must be validated. Windows ARM64 and Linux ARM64 will follow after dependency checks and suitable tests are available. Alpine/musl and older systems are outside this initial matrix.

Minimum requirements come from [Qt 6.11 platforms](https://doc.qt.io/qtforpython-6/overviews/qtdoc-supported-platforms.html) and [PySide6 6.11.2 wheels](https://pypi.org/project/PySide6/6.11.2/). Linux ARM64 binaries for this version require glibc 2.39+.

## 3. Project directory and files

Retain the existing directory and workspace. On other machines, the equivalent location is `~/projects/Trackfolio`, or `%USERPROFILE%\projects\Trackfolio` on Windows. The project must also work elsewhere: no personal paths belong in shared configuration.

Planned structure; reserve application modules without implementing features yet:

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

Use an installable package with a `src` layout so imports behave identically outside the repository root. Declare an exact build backend version in `[build-system]`. Document the planned architecture; add functional tests when there is behavior to test.

`.gitignore` excludes `.venv`, caches, build outputs, local configuration, local databases and user music. Deliberately included test data must be distinguishable from local data. `.gitattributes` and `.editorconfig` define UTF-8 and LF for code and configuration, with exceptions for files requiring other treatment.

## 4. Dependencies and isolation

| Area | Planned dependencies | Reason |
| --- | --- | --- |
| Persistence | SQLAlchemy 2.x and Alembic | SQLite access and schema evolution |
| Music metadata | Mutagen | FLAC and MP3 reading/writing |
| User directories | platformdirs | Portable configuration, cache and database locations |
| `gui` extra | PySide6 6.11.2 | Qt 6 without forcing the core to install desktop dependencies |
| `dev` group | pytest, Ruff and mypy | Tests, formatting, analysis and types |

Mutagen declares support for [FLAC and MP3](https://mutagen.readthedocs.io/en/latest/). Metadata editing does not require FFmpeg; playback or conversion would be later features with their own requirements.

Use SQLite through `sqlite3`, included in standard CPython distributions. Diagnostics verify its availability and operation; no database server or `sqlite3` executable is required.

Track `pyproject.toml`, `.python-version` and `uv.lock` in Git. The lock contains concrete dependency versions and hashes, including platform variants. Pin build dependencies in their configuration too. Each PC generates its own `.venv`; never move it with the project. See [uv project layout](https://docs.astral.sh/uv/concepts/projects/layout/) and [Python environment portability](https://docs.python.org/3/library/venv.html).

Configure `python-preference = "only-managed"` and use `required-environments` for the supported architectures. The latter helps detect missing wheels for packages without source distributions; actual installation checks remain necessary. [uv settings](https://docs.astral.sh/uv/reference/settings/).

Generate `uv.lock` during initial setup. Subsequent installation uses `uv sync --locked`: a manifest/lock mismatch causes an error. Updates are explicit and reviewed with both files. `--frozen` skips consistency checks and is not the normal onboarding command. [uv synchronization](https://docs.astral.sh/uv/concepts/projects/sync/).

## 5. Installing missing prerequisites

The initial tools are already present on this PC. The project environment, managed Python installation and dependency checks are still needed.

On another PC:

1. Install Git using the [official instructions for each system](https://git-scm.com/install/). Check `git --version`.
2. Install the pinned `uv` version with one of the commands below. Reopen the terminal if needed and check `uv --version`.
3. Clone the repository or copy its sources and run `uv python install` from the root. It reads `.python-version`; global Python need not match project Python. [Installing Python with uv](https://docs.astral.sh/uv/guides/install-python/).
4. For VS Code development, install it from the [official download](https://code.visualstudio.com/download) and accept the workspace's recommended extensions. The editor is optional for running Trackfolio.
5. To manage GitHub from the terminal, optionally install [GitHub CLI](https://github.com/cli/cli#installation) and run `gh auth login`. GitHub CLI is not an application dependency.

Linux/macOS `uv` installation:

```sh
curl -LsSf https://astral.sh/uv/0.12.10/install.sh | sh
```

Windows `uv` installation from PowerShell:

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/0.12.10/install.ps1 | iex"
```

These are the official mechanisms for [installing a specific uv version](https://docs.astral.sh/uv/getting-started/installation/). Do not install project packages globally with `pip`.

PySide6 wheels include Qt, so the full Qt SDK is not required. [Installing Qt for Python](https://doc.qt.io/qtforpython-6/gettingstarted.html). GNU/Linux may lack system graphics libraries: `uv` does not install those packages. Diagnostics identify failures and `docs/environment.md` maps missing libraries to packages and installation commands by distribution, following [Qt 6.11 Linux requirements](https://doc.qt.io/qt-6.11/linux-requirements.html).

For example, a missing `libxcb-cursor.so.0` requires `sudo apt install libxcb-cursor0` on Ubuntu/Debian or `sudo pacman -S --needed xcb-util-cursor` on Arch and derivatives. Document any additional backend dependencies found during testing. These commands address that specific library; recheck the GUI afterward. References: [Ubuntu package](https://packages.ubuntu.com/noble/libxcb-cursor0), [Arch package files](https://archlinux.org/packages/extra/x86_64/xcb-util-cursor/files/).

## 6. Setup and diagnostics before development

Create two portable Python tools:

- `bootstrap.py`: checks `uv` and its version, installs the pinned Python and syncs from the lock. Supports core or GUI setup, is repeatable and propagates errors. External calls use structured arguments without Bash, Make or `shell=True` dependencies.
- `doctor.py`: checks interpreter, OS, architecture, installed versions, imports, a temporary SQLite operation, resources and GUI-specific requirements. Shows actionable errors and returns nonzero when a mandatory requirement is missing.

Run Qt diagnostics in a subprocess because graphics plugin failures can abort the process. Distinguish headless (`offscreen`) checks from actual desktop checks; the former does not prove that X11, Wayland or native backends work.

Once the manifest, lock and scripts exist, shared commands for all three platforms are:

```sh
uv python install
uv sync --locked --extra gui --group dev
uv run --locked --extra gui python scripts/doctor.py --gui
code Trackfolio.code-workspace
```

To develop the core without Qt:

```sh
uv python install
uv sync --locked --group dev
uv run --locked python scripts/doctor.py --core
```

These commands describe the planned environment and cannot yet run against this directory: required files will be created when executing the plan. Keep the `gui` extra explicit in tasks that need it. Extras are optional and `dev` contains development tools, following [uv dependency management](https://docs.astral.sh/uv/concepts/projects/dependencies/).

## 7. Git and GitHub preparation

Initialize Git after generating infrastructure files:

```sh
git init -b main
git config --local core.autocrlf false
git config --local pull.ff only
git config --get user.name
git config --get user.email
```

Retain the configured identity. On a machine without one, configure the developer's commit name and email with `git config --local user.name` and `git config --local user.email`. Do not put these settings in shared files. [Git configuration](https://git-scm.com/book/en/v2/Getting-Started-First-Time-Git-Setup).

Review files for inclusion and make an initial commit containing only the environment and documentation. The initial proposal for subsequently creating the remote is a private repository:

```sh
gh repo create Evilchuck666/Trackfolio --private --source=. --remote=origin
git push -u origin main
```

Visibility is a proposal; public visibility may be chosen during execution. Before creating the remote, check again whether it exists. If it does, configure its URL as `origin` and inspect its history before uploading commits. Manage credentials through GitHub CLI or Git's credential manager; never write them into the project. [Creating repositories with GitHub CLI](https://cli.github.com/manual/gh_repo_create).

## 8. VS Code workspace

Extend the existing workspace, retaining `folders: [{"path": "."}]`:

- Discover local `.venv`, with explicit selection through “Python: Select Interpreter” if a different local preference exists. Do not pin `/home/...`, `.venv/bin/python` or paths that fail on Windows.
- Recommend Python, Pylance, Python Debugger and Ruff. Configure formatting and analysis in `pyproject.toml`, shared by terminal and editor.
- Add `process` tasks with executable `uv` and separate arguments for setup, diagnostics, formatting checks and tests when available. Set working directory to `${workspaceFolder}`.
- Defer application launch configuration until its entry point exists.

The editor supports `.venv` discovery; explicit user preferences can override defaults. [Python environments in VS Code](https://code.visualstudio.com/docs/python/environments).

## 9. Architecture the environment must preserve

Dependency direction: interfaces → use cases → domain. Infrastructure adapters implement inward-defined contracts; the startup entry point wires the components.

`domain` contains entities and rules; `application`, use cases and contracts; `infrastructure`, SQLAlchemy persistence and metadata/file access; `interfaces/gui`, presentation and event translation. Domain and use cases must not import Qt or expose widgets, signals, `QObject` or ORM models as public contracts.

The GUI requests operations and displays results. A future CLI/TUI or API uses the same use cases. A future server accesses music files and SQLite on its own machine; the remote frontend consumes the API. Preserve this possibility without developing those interfaces during setup.

Path policy uses `pathlib`, library identifiers and root-relative track paths. Music roots may vary by machine. Configuration and database files belong in suitable OS-specific user directories; visual resources ship with the application.

## 10. Planned consistent appearance

Use Qt Widgets with explicit **Fusion** style, a custom palette and stylesheet, and packaged fonts and icons. Choose Qt dialog implementations on surfaces requiring consistent appearance. [Qt styles](https://doc.qt.io/qt-6/qstylefactory.html).

The visual criterion is the same application-area design: controls, colors, typography, icons and layout. Systems may differ in rasterization and DPI scaling. If “identical” includes the frame and title bar, custom decorations must be implemented and their window/accessibility behavior validated; Fusion alone does not meet that requirement.

## 11. Validation and completion criteria

Prepare GitHub Actions to recreate the environment from scratch on Windows x86-64, Linux x86-64 and macOS Intel/ARM using pinned Python and `uv`. Pin actions by revision and explicitly select available runner images. Follow [uv's official GitHub Actions integration](https://docs.astral.sh/uv/guides/integration/github/).

Before application development starts:

1. The repository contains the manifest, lock, Python version, documentation and portable workspace.
2. A clean copy or clone without `.venv` installs all locked dependencies across the target matrix.
3. Repeated setup preserves the lock and expected versions; an outdated lock produces a clear error.
4. Diagnostics check SQLite and dependencies with project Python.
5. Core setup works without installing PySide6 or requiring a desktop.
6. Qt opens a minimal window and processes events on tested desktops. Linux includes X11 and Wayland checks; headless tests are recorded separately.
7. VS Code selects the local environment and tasks work without personal paths or a specific shell dependency.
8. Missing prerequisites produce specific installation instructions and useful exit codes.

Record results by OS and architecture. This document does not claim Windows and macOS have already passed: portability requires executing that matrix.

Execution order: project files → manifest and lock → setup/diagnostics → workspace → Git and remote → cross-platform validation. Trackfolio development begins once this infrastructure is verified.
