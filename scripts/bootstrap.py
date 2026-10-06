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


def configuration(root: Path) -> tuple[str, str]:
    """Read exact tool/interpreter pins and require the committed lock file."""
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
    if not isinstance(required_uv, str) or not re.fullmatch(r"==\d+\.\d+\.\d+", required_uv):
        raise BootstrapError("tool.uv.required-version debe fijar una versión exacta (==X.Y.Z).")
    if not re.fullmatch(r"\d+\.\d+\.\d+", python_version):
        raise BootstrapError(".python-version debe fijar una versión CPython exacta (X.Y.Z).")
    if not isinstance(lock.get("package"), list) or not lock["package"]:
        raise BootstrapError("uv.lock no contiene paquetes. Recupera el lock del repositorio.")
    return required_uv[2:], python_version


def uv_install_help(version: str) -> str:
    """Provide instructions without executing a remote installation script."""
    return (
        f"Instala uv {version} y vuelve a abrir la terminal.\n"
        f"Linux/macOS: curl -LsSf https://astral.sh/uv/{version}/install.sh | sh\n"
        "Windows PowerShell: powershell -ExecutionPolicy ByPass -c "
        f'"irm https://astral.sh/uv/{version}/install.ps1 | iex"'
    )


def check_uv(required_version: str) -> str:
    executable = shutil.which("uv")
    if executable is None:
        raise BootstrapError(f"No se encuentra uv en PATH.\n{uv_install_help(required_version)}")
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
    if actual_version != required_version:
        raise BootstrapError(
            f"El proyecto requiere uv {required_version}; se encontró {actual_version}.\n"
            f"{uv_install_help(required_version)}"
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


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        required_uv, python_version = configuration(PROJECT_ROOT)
        executable = check_uv(required_uv)
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
