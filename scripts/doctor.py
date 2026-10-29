"""Diagnose the reproducible core environment and, optionally, its Qt desktop."""

from __future__ import annotations

import argparse
import hashlib
import importlib
import importlib.metadata
import importlib.resources
import json
import platform
import re
import signal
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:
    sys.exit(
        "Esta herramienta necesita Python 3.11 o posterior. Usa: "
        "uv run --locked python scripts/doctor.py --core"
    )

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CORE_DISTRIBUTIONS = ("SQLAlchemy", "alembic", "mutagen", "platformdirs")
GUI_DISTRIBUTIONS = ("PySide6", "PySide6-Addons", "PySide6-Essentials", "shiboken6")
CORE_MODULES = ("trackfolio", "sqlalchemy", "alembic", "mutagen", "platformdirs", "sqlite3")
QT_PROBE_PREFIX = "TRACKFOLIO_QT_PROBE="
QT_PROBE = """
import json
import sys
from trackfolio.interfaces.gui.probe import run_probe

print("TRACKFOLIO_QT_PROBE=" + json.dumps(run_probe(sys.argv[1:])))
"""


@dataclass(frozen=True)
class CheckResult:
    name: str
    ok: bool
    detail: str


def normalize_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def read_lock(root: Path) -> dict[str, set[str]]:
    content = tomllib.loads((root / "uv.lock").read_text(encoding="utf-8"))
    packages = content.get("package")
    if not isinstance(packages, list) or not packages:
        raise ValueError("uv.lock no contiene una lista de paquetes.")
    versions: dict[str, set[str]] = {}
    for package in packages:
        if not isinstance(package, dict):
            raise ValueError("uv.lock contiene un paquete que no es una tabla TOML.")
        name, version = package.get("name"), package.get("version")
        if not isinstance(name, str) or not isinstance(version, str):
            raise ValueError("uv.lock contiene un paquete sin nombre o versión.")
        versions.setdefault(normalize_name(name), set()).add(version)
    return versions


def check_python(root: Path) -> CheckResult:
    try:
        expected = (root / ".python-version").read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError) as exc:
        return CheckResult("Python", False, f"No se puede leer .python-version: {exc}")
    actual = platform.python_version()
    if not re.fullmatch(r"\d+\.\d+\.\d+", expected):
        return CheckResult("Python", False, ".python-version debe fijar una versión exacta X.Y.Z.")
    if sys.implementation.name != "cpython" or actual != expected:
        return CheckResult(
            "Python",
            False,
            f"Se requiere CPython {expected}; se usa {sys.implementation.name} {actual}. "
            "Ejecuta uv python install y luego uv run --locked python scripts/doctor.py.",
        )
    return CheckResult("Python", True, f"CPython {actual}: {sys.executable}")


def check_versions(root: Path, gui: bool) -> list[CheckResult]:
    try:
        locked = read_lock(root)
    except (OSError, UnicodeError, ValueError, tomllib.TOMLDecodeError) as exc:
        return [
            CheckResult(
                "uv.lock",
                False,
                f"No se puede comprobar el lock: {exc}. Recupera uv.lock del repositorio.",
            )
        ]
    names = CORE_DISTRIBUTIONS + (GUI_DISTRIBUTIONS if gui else ())
    results = []
    sync_command = "uv sync --locked --group dev" + (" --extra gui" if gui else "")
    for name in names:
        expected = locked.get(normalize_name(name))
        if not expected:
            results.append(CheckResult(name, False, f"El paquete no aparece en uv.lock: {name}."))
            continue
        try:
            actual = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            results.append(CheckResult(name, False, f"No está instalado. Ejecuta {sync_command}."))
            continue
        ok = actual in expected
        detail = (
            actual
            if ok
            else (
                f"Instalado {actual}; el lock exige {', '.join(sorted(expected))}. "
                f"Ejecuta {sync_command}."
            )
        )
        results.append(CheckResult(name, ok, detail))
    return results


def check_imports() -> list[CheckResult]:
    results = []
    for name in CORE_MODULES:
        try:
            importlib.import_module(name)
        except Exception as exc:
            results.append(
                CheckResult(
                    f"Import {name}",
                    False,
                    f"{type(exc).__name__}: {exc}. Ejecuta uv sync --locked --group dev. "
                    "Si falla sqlite3, reinstala el CPython administrado con uv python install.",
                )
            )
        else:
            results.append(CheckResult(f"Import {name}", True, "Disponible"))
    return results


def check_sqlite() -> CheckResult:
    try:
        import sqlite3

        from sqlalchemy import URL, create_engine, text

        with tempfile.TemporaryDirectory(prefix="trackfolio-doctor-") as directory:
            database = Path(directory) / "roundtrip.sqlite3"
            engine = create_engine(URL.create("sqlite", database=str(database)))
            try:
                with engine.begin() as connection:
                    connection.execute(
                        text("CREATE TABLE checks (id INTEGER PRIMARY KEY, name TEXT)")
                    )
                    connection.execute(
                        text("INSERT INTO checks (name) VALUES (:name)"),
                        {"name": "Trackfolio · música FLAC/MP3"},
                    )
                with engine.connect() as connection:
                    actual: object = connection.execute(
                        text("SELECT name FROM checks")
                    ).scalar_one()
                if actual != "Trackfolio · música FLAC/MP3":
                    raise RuntimeError("La lectura no coincide con la escritura SQLite.")
            finally:
                engine.dispose()
        return CheckResult(
            "SQLite", True, f"SQLite {sqlite3.sqlite_version}; transacción y lectura OK"
        )
    except Exception as exc:
        return CheckResult(
            "SQLite",
            False,
            f"{type(exc).__name__}: {exc}. Comprueba el Python administrado, "
            "uv sync --locked --group dev y permisos del directorio temporal del sistema.",
        )


def check_resources() -> CheckResult:
    try:
        resources = importlib.resources.files("trackfolio.resources")
        manifest = json.loads(resources.joinpath("manifest.json").read_text(encoding="utf-8"))
        assets = manifest["sha256"]
        required = {
            "stylesheet.qss",
            "fonts/Inter-Regular.ttf",
            "fonts/Inter-SemiBold.ttf",
            "fonts/LICENSE.txt",
            *(
                f"icons/{name}.svg"
                for name in (
                    "app",
                    "open",
                    "import",
                    "refresh",
                    "close",
                    "minimize",
                    "maximize",
                    "restore",
                )
            ),
        }
        if not isinstance(assets, dict) or set(assets) != required:
            raise ValueError("El manifiesto no enumera todos los recursos esperados.")
        for name, digest in assets.items():
            if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
                raise ValueError(f"SHA-256 inválido para {name}.")
            content = resources.joinpath(*name.split("/")).read_bytes()
            if not content or hashlib.sha256(content).hexdigest() != digest:
                raise ValueError(f"El recurso {name} está vacío o su SHA-256 no coincide.")
    except Exception as exc:
        return CheckResult(
            "Recursos",
            False,
            f"No se pueden validar los recursos empaquetados de trackfolio.resources: {exc}. "
            "Comprueba los recursos del paquete y repite uv sync --locked.",
        )
    return CheckResult(
        "Recursos",
        True,
        f"{len(required)} recursos accesibles; fuentes, licencia, SVG y QSS verificados",
    )


def version_tuple(value: str) -> tuple[int, ...]:
    return tuple(int(component) for component in re.findall(r"\d+", value))


def check_gui_platform() -> CheckResult:
    system, machine = platform.system(), platform.machine().lower()
    detail = f"{system} {platform.release()} ({machine})"
    if system == "Windows":
        if machine not in ("amd64", "x86_64"):
            return CheckResult("Plataforma GUI", False, f"{detail}. Se requiere Windows x86-64.")
        windows_version = version_tuple(platform.version())
        if len(windows_version) < 3 or windows_version < (10, 0, 17763):
            return CheckResult(
                "Plataforma GUI", False, f"{detail}. Se requiere Windows 10 1809 o posterior."
            )
    elif system == "Darwin":
        mac_version = platform.mac_ver()[0]
        if machine not in ("x86_64", "arm64") or version_tuple(mac_version) < (13,):
            return CheckResult(
                "Plataforma GUI", False, f"{detail}. Se requiere macOS 13+ Intel o Apple Silicon."
            )
        detail = f"macOS {mac_version} ({machine})"
    elif system == "Linux":
        libc, libc_version = platform.libc_ver()
        if (
            machine not in ("x86_64", "amd64")
            or libc != "glibc"
            or version_tuple(libc_version) < (2, 34)
        ):
            return CheckResult(
                "Plataforma GUI",
                False,
                f"{detail}; libc={libc or 'desconocida'} {libc_version}. "
                "Se requiere GNU/Linux x86-64 con glibc 2.34+. Consulta docs/environment.md.",
            )
        detail += f"; glibc {libc_version}"
    else:
        return CheckResult(
            "Plataforma GUI",
            False,
            f"{detail}. La matriz inicial cubre Windows, macOS y GNU/Linux.",
        )
    return CheckResult("Plataforma GUI", True, detail)


def qt_failure_help(output: str) -> str:
    lowered = output.lower()
    if "no module named" in lowered:
        return "Instala Qt con uv sync --locked --group dev --extra gui."
    if any(
        fragment in lowered
        for fragment in (
            "could not connect to display",
            "failed to create wl_display",
            "xdg_runtime_dir",
        )
    ):
        return (
            "Comprueba DISPLAY o WAYLAND_DISPLAY/XDG_RUNTIME_DIR y la sesión gráfica. "
            "Para CI usa --platform offscreen o xvfb-run con --platform xcb; "
            "offscreen no valida el escritorio real."
        )
    if platform.system() == "Linux":
        return (
            "Comprueba las bibliotecas del plugin y la sesión gráfica; "
            "consulta docs/environment.md. "
            "Si falta libxcb-cursor.so.0: Debian/Ubuntu: sudo apt install libxcb-cursor0; "
            "Arch: sudo pacman -S --needed xcb-util-cursor. "
            "Si falta otra .so, instala el paquete de sistema indicado en esa documentación."
        )
    return (
        "Comprueba el sistema mínimo y el escritorio. Reinstala las dependencias con "
        "uv sync --locked --group dev --extra gui; consulta docs/environment.md."
    )


def captured_text(value: str | bytes | None) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value or ""


def check_qt(qt_platform: str | None, timeout: float) -> CheckResult:
    command = [sys.executable, "-c", QT_PROBE]
    if qt_platform:
        command.extend(["-platform", qt_platform])
    try:
        result = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        output = captured_text(exc.stderr).strip()
        return CheckResult(
            "Qt/Fusion",
            False,
            f"Qt superó el timeout de {timeout:g} s; se ha detenido el subproceso. "
            f"{output[-4000:]} {qt_failure_help(output)}",
        )
    except OSError as exc:
        return CheckResult("Qt/Fusion", False, f"No se pudo iniciar el subproceso Qt: {exc}")
    if result.returncode != 0:
        cause = f"código {result.returncode}"
        if result.returncode < 0:
            try:
                cause = f"señal {signal.Signals(-result.returncode).name}"
            except ValueError:
                cause = f"señal {-result.returncode}"
        output = (result.stderr or result.stdout).strip()
        return CheckResult(
            "Qt/Fusion",
            False,
            f"El subproceso Qt terminó con {cause}. {output[-4000:]} {qt_failure_help(output)}",
        )
    payload = next(
        (
            line.removeprefix(QT_PROBE_PREFIX)
            for line in result.stdout.splitlines()
            if line.startswith(QT_PROBE_PREFIX)
        ),
        None,
    )
    try:
        report = json.loads(payload or "")
        backend, style, qt_version = report["platform"], report["style"], report["qt_version"]
        if not all(isinstance(value, str) for value in (backend, style, qt_version)):
            raise ValueError("El informe contiene tipos incorrectos.")
        if style.lower() != "fusion" or report.get("events") is not True:
            raise ValueError("No se comprobó Fusion o el ciclo de eventos.")
        if report.get("imported") is not True or report.get("edited") is not True:
            raise ValueError("No se comprobó la importación y edición del catálogo.")
    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        return CheckResult("Qt/Fusion", False, f"El subproceso no confirmó la prueba Qt: {exc}")
    scope = (
        "Prueba sin pantalla; no confirma el escritorio real."
        if backend in ("offscreen", "minimal")
        else "Ventana del backend gráfico y ciclo de eventos comprobados."
    )
    return CheckResult(
        "Qt/Fusion",
        True,
        f"Qt {qt_version}, Fusion, backend {backend}; importación y edición comprobadas. {scope}",
    )


def positive_timeout(value: str) -> float:
    timeout = float(value)
    if not 0 < timeout <= 300:
        raise argparse.ArgumentTypeError("El timeout debe estar entre 0 y 300 segundos.")
    return timeout


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--core", action="store_true", help="Comprobar sólo el núcleo (por defecto).")
    mode.add_argument("--gui", action="store_true", help="Comprobar también la GUI Qt.")
    parser.add_argument("--platform", choices=("offscreen", "xcb", "wayland"))
    parser.add_argument("--qt-timeout", type=positive_timeout, default=15.0, metavar="SEGUNDOS")
    args = parser.parse_args(argv)
    if args.platform and not args.gui:
        parser.error("--platform necesita --gui.")
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    results = [check_python(PROJECT_ROOT)]
    results.extend(check_versions(PROJECT_ROOT, args.gui))
    results.extend(check_imports())
    results.extend([check_sqlite(), check_resources()])
    if args.gui:
        results.extend([check_gui_platform(), check_qt(args.platform, args.qt_timeout)])
    for result in results:
        print(f"{'OK' if result.ok else 'ERROR'} · {result.name}: {result.detail}", flush=True)
    failures = sum(not result.ok for result in results)
    print(f"Diagnóstico {'GUI' if args.gui else 'núcleo'}: {failures} error(es).")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
