"""Prepare the locked development environment without a platform-specific shell."""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:
    sys.exit(
        "Esta herramienta necesita Python 3.11 o posterior. Usa: "
        "uv run --no-project --python 3.13.15 python scripts/bootstrap.py"
    )

PROJECT_ROOT = Path(__file__).resolve().parents[1]


class BootstrapError(Exception):
    """A prerequisite cannot be satisfied using the checked-in configuration."""


def version_tuple(version: str) -> tuple[int, ...]:
    """Compare stable versions numerically, treating X.Y as X.Y.0."""
    parts = tuple(int(part) for part in version.split("."))
    return parts + (0,) * (3 - len(parts))


def uv_version_range(requirement: str) -> tuple[str, str]:
    """Read the inclusive minimum and exclusive maximum without extra dependencies."""
    match = re.fullmatch(
        r">=\s*([0-9]+\.[0-9]+\.[0-9]+)\s*,\s*<\s*([0-9]+\.[0-9]+(?:\.[0-9]+)?)",
        requirement.strip(),
    )
    if match is None:
        raise BootstrapError("tool.uv.required-version debe definir un rango como >=0.12.10,<0.13.")
    minimum, maximum = match.groups()
    if version_tuple(minimum) >= version_tuple(maximum):
        raise BootstrapError(
            "tool.uv.required-version debe tener un mínimo inferior al máximo exclusivo."
        )
    return minimum, maximum


def configuration(root: Path) -> tuple[str, str]:
    """Read the uv range and exact interpreter pin; require the committed lock file."""
    try:
        manifest = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
        python_version = (root / ".python-version").read_text(encoding="utf-8").strip()
        lock = tomllib.loads((root / "uv.lock").read_text(encoding="utf-8"))
    except (OSError, UnicodeError, tomllib.TOMLDecodeError) as exc:
        raise BootstrapError(
            f"No se puede leer la configuración versionada: {exc}. "
            "Recupera pyproject.toml, .python-version y uv.lock del repositorio."
        ) from exc
    tool = manifest.get("tool", {})
    uv_settings = tool.get("uv", {}) if isinstance(tool, dict) else {}
    required_uv = uv_settings.get("required-version", "") if isinstance(uv_settings, dict) else ""
    if not isinstance(required_uv, str):
        raise BootstrapError("tool.uv.required-version debe definir un rango como >=0.12.10,<0.13.")
    uv_version_range(required_uv)
    if not re.fullmatch(r"\d+\.\d+\.\d+", python_version):
        raise BootstrapError(".python-version debe fijar una versión CPython exacta (X.Y.Z).")
    if not isinstance(lock.get("package"), list) or not lock["package"]:
        raise BootstrapError("uv.lock no contiene paquetes. Recupera el lock del repositorio.")
    return required_uv, python_version


def uv_install_help(version: str) -> str:
    """Suggest the minimum supported version without executing a remote installer."""
    return (
        f"Instala uv {version} (versión mínima admitida) o una versión compatible "
        "y vuelve a abrir la terminal.\n"
        f"Linux/macOS: curl -LsSf https://astral.sh/uv/{version}/install.sh | sh\n"
        "Windows PowerShell: powershell -ExecutionPolicy ByPass -c "
        f'"irm https://astral.sh/uv/{version}/install.ps1 | iex"'
    )


def check_uv(required_version: str, executable: str | None = None) -> str:
    """Require a stable uv release within the configured half-open range."""
    minimum, maximum = uv_version_range(required_version)
    executable = executable or shutil.which("uv")
    if executable is None:
        raise BootstrapError(
            f"No se encuentra uv en PATH. Se requiere uv {required_version}.\n"
            f"{uv_install_help(minimum)}"
        )
    try:
        result = subprocess.run(
            [executable, "--version"],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise BootstrapError(f"No se puede ejecutar uv --version: {exc}") from exc
    match = re.match(r"uv (\d+\.\d+\.\d+)(?:\s|$)", result.stdout.strip())
    if result.returncode != 0 or match is None:
        raise BootstrapError(
            f"uv --version falló o produjo una respuesta desconocida: "
            f"{result.stderr.strip() or result.stdout.strip()}"
        )
    actual_version = match.group(1)
    if not version_tuple(minimum) <= version_tuple(actual_version) < version_tuple(maximum):
        raise BootstrapError(
            f"El proyecto requiere uv {required_version}; se encontró {actual_version}.\n"
            f"{uv_install_help(minimum)}"
        )
    return executable


def positive_timeout(value: str) -> float:
    timeout = float(value)
    if not 0 < timeout <= 300:
        raise argparse.ArgumentTypeError("El timeout debe estar entre 0 y 300 segundos.")
    return timeout


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--core", action="store_true", help="Preparar sólo el núcleo (por defecto).")
    mode.add_argument("--gui", action="store_true", help="Preparar también Qt y comprobar la GUI.")
    parser.add_argument("--platform", choices=("offscreen", "xcb", "wayland"))
    parser.add_argument("--qt-timeout", type=positive_timeout, default=15.0, metavar="SEGUNDOS")
    args = parser.parse_args(argv)
    if args.platform and not args.gui:
        parser.error("--platform necesita --gui.")
    return args


def main(argv: list[str] | None = None, *, executable: str | None = None) -> int:
    args = parse_args(argv)
    try:
        required_uv, python_version = configuration(PROJECT_ROOT)
        executable = (
            check_uv(required_uv, executable=executable)
            if executable is not None
            else check_uv(required_uv)
        )
    except BootstrapError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    common = ["--locked", "--group", "dev"]
    if args.gui:
        common.extend(["--extra", "gui"])
    doctor_args = ["--gui" if args.gui else "--core"]
    if args.gui:
        doctor_args.extend(["--qt-timeout", str(args.qt_timeout)])
    if args.platform:
        doctor_args.extend(["--platform", args.platform])
    commands = [
        [executable, "python", "install", python_version],
        [executable, "sync", *common],
        [executable, "run", *common, "python", "scripts/doctor.py", *doctor_args],
    ]
    for command in commands:
        print(f"Ejecutando: {' '.join(command)}", flush=True)
        try:
            result = subprocess.run(command, cwd=PROJECT_ROOT, check=False)
        except OSError as exc:
            print(f"ERROR: No se pudo ejecutar {command[1]}: {exc}", file=sys.stderr)
            return 1
        if result.returncode != 0:
            print(
                f"ERROR: {command[1]} terminó con código {result.returncode}. "
                "Resuelve el error anterior y repite la preparación. "
                "Si el lock está desactualizado, un responsable debe actualizarlo con uv lock.",
                file=sys.stderr,
            )
            return result.returncode if result.returncode > 0 else 1
    print("Entorno preparado y comprobado desde uv.lock.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
