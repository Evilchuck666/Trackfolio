# Contributing to Trackfolio

## Getting started

Download or clone the `gui` branch and set up the environment from the root. You do not need to install uv or Python beforehand:

```sh
bash setup.sh
```

On Windows, use `powershell -NoProfile -ExecutionPolicy Bypass -File .\setup.ps1`. Use `--core` to develop without Qt and `--skip-editor` to skip VS Code setup. System installations require confirmation; `--non-interactive` does not prompt. See [launcher options](docs/environment.md#single-command-setup).

Open `Trackfolio.code-workspace` in VS Code, or use `bash setup.sh --open-code` (the same arguments apply in PowerShell). Select the local `.venv` interpreter if the editor does not detect it.

The environment uses uv-managed CPython 3.13.15 and dependencies pinned in `uv.lock`. It reuses any uv compatible with `>=0.13.4,<0.14`; if missing, it downloads it into `.tools/uv` without editing shell profiles. Do not install project packages into global Python or copy `.venv` or `.tools` from another machine. `uv run` commands do not require environment activation; if uv is not in your terminal's `PATH`, prefix its arguments with `bash setup.sh --run-uv` or use the PowerShell launcher.

## Code changes

Follow [docs/architecture.md](docs/architecture.md): the domain and use cases must not import Qt, SQLAlchemy or Mutagen. ORM models and widgets belong in adapters. Every interface uses the same use cases.

Use `pathlib` for paths. Avoid developer-specific absolute paths, Bash-dependent commands, `shell=True`, and access to real music or databases in tests. Shared scripts must work on Windows, macOS and GNU/Linux.

Before proposing a change, run the relevant checks:

```sh
uv run --locked ruff check .
uv run --locked ruff format --check .
uv run --locked mypy
uv run --locked pytest
```

If you change dependencies or diagnostics, also rerun `doctor.py --core` and, when applicable, `doctor.py --gui` with the `gui` extra. Record the OS, architecture and graphical backend tested; distinguish `offscreen` from X11, Wayland and native desktops. Do not claim one platform is validated based only on another.

## Updating dependencies

Direct requirements are declared in `pyproject.toml`; resolved versions are in `uv.lock`. Normal commands use `--locked`, so an outdated lockfile fails without being changed. Do not use `--frozen` to hide a mismatch.

To add a core, GUI or development dependency:

```sh
uv add package
uv add --optional gui package
uv add --group dev package
```

These commands are alternatives; replace `package` and run the appropriate one. To deliberately update an existing dependency:

```sh
uv lock --upgrade-package package-name
uv sync --locked --extra gui --group dev
uv run --locked --extra gui python scripts/doctor.py --gui
```

Review the manifest and lockfile diff, run the checks, and include both files when they change. Patch updates of uv within `>=0.13.4,<0.14` do not require changing the requirement; verify setup and tests with the chosen version. Widening that range or updating CPython, the build backend or PySide6 requires reviewing the relevant configuration, scripts and documentation and verifying the matrix again. `uv_build==0.12.10` is the build backend, not a requirement on the installed uv executable. Do not widen `requires-python` without validating the new interpreter.

## Git and local data

Configure your identity when cloning if it is not already configured:

```sh
git config --local user.name "Your name"
git config --local user.email "your-email@example.com"
git config --local core.autocrlf false
git config --local pull.ff only
```

`.gitattributes` defines repository line endings and `.editorconfig` maintains basic formatting. `.gitignore` excludes environments, caches, music, databases and secrets. Do not force their inclusion. Future test data must be small, artificial or redistributable, and added explicitly.

Include the changed behavior and checks performed in the change description. This phase prepares the environment: new music features and interfaces will be developed in subsequent changes.
