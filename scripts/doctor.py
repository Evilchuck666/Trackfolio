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
        "This tool requires Python 3.11 or later. Use: "
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
        raise ValueError("uv.lock does not contain a package list.")
    versions: dict[str, set[str]] = {}
    for package in packages:
        if not isinstance(package, dict):
            raise ValueError("uv.lock contains a package that is not a TOML table.")
        name, version = package.get("name"), package.get("version")
        if not isinstance(name, str) or not isinstance(version, str):
            raise ValueError("uv.lock contains a package without a name or version.")
        versions.setdefault(normalize_name(name), set()).add(version)
    return versions


def check_python(root: Path) -> CheckResult:
    try:
        expected = (root / ".python-version").read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError) as exc:
        return CheckResult("Python", False, f"Cannot read .python-version: {exc}")
    actual = platform.python_version()
    if not re.fullmatch(r"\d+\.\d+\.\d+", expected):
        return CheckResult("Python", False, ".python-version must pin an exact X.Y.Z version.")
    if sys.implementation.name != "cpython" or actual != expected:
        return CheckResult(
            "Python",
            False,
            f"Required CPython version: {expected}; using {sys.implementation.name} {actual}. "
            "Run uv python install, then uv run --locked python scripts/doctor.py.",
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
                f"Cannot check the lockfile: {exc}. Restore uv.lock from the repository.",
            )
        ]
    names = CORE_DISTRIBUTIONS + (GUI_DISTRIBUTIONS if gui else ())
    results = []
    sync_command = "uv sync --locked --group dev" + (" --extra gui" if gui else "")
    for name in names:
        expected = locked.get(normalize_name(name))
        if not expected:
            results.append(CheckResult(name, False, f"Package not listed in uv.lock: {name}."))
            continue
        try:
            actual = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            results.append(CheckResult(name, False, f"Not installed. Run {sync_command}."))
            continue
        ok = actual in expected
        detail = (
            actual
            if ok
            else (
                f"Installed {actual}; the lockfile requires {', '.join(sorted(expected))}. "
                f"Run {sync_command}."
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
                    f"{type(exc).__name__}: {exc}. Run uv sync --locked --group dev. "
                    "If sqlite3 fails, reinstall managed CPython with uv python install.",
                )
            )
        else:
            results.append(CheckResult(f"Import {name}", True, "Available"))
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
                        {"name": "Trackfolio · FLAC/MP3 music"},
                    )
                with engine.connect() as connection:
                    actual: object = connection.execute(
                        text("SELECT name FROM checks")
                    ).scalar_one()
                if actual != "Trackfolio · FLAC/MP3 music":
                    raise RuntimeError("The SQLite read does not match the write.")
            finally:
                engine.dispose()
        return CheckResult(
            "SQLite", True, f"SQLite {sqlite3.sqlite_version}; transaction and read OK"
        )
    except Exception as exc:
        return CheckResult(
            "SQLite",
            False,
            f"{type(exc).__name__}: {exc}. Check managed Python, "
            "uv sync --locked --group dev and system temporary directory permissions.",
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
                    "check",
                    "edit",
                    "tag",
                    "disc",
                    "file",
                    "report",
                    "close",
                    "minimize",
                    "maximize",
                    "restore",
                )
            ),
        }
        if not isinstance(assets, dict) or set(assets) != required:
            raise ValueError("The manifest does not list all expected resources.")
        for name, digest in assets.items():
            if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
                raise ValueError(f"Invalid SHA-256 for {name}.")
            content = resources.joinpath(*name.split("/")).read_bytes()
            if not content or hashlib.sha256(content).hexdigest() != digest:
                raise ValueError(f"Resource {name} is empty or its SHA-256 does not match.")
    except Exception as exc:
        return CheckResult(
            "Resources",
            False,
            f"Cannot validate packaged trackfolio.resources assets: {exc}. "
            "Check the package resources and run uv sync --locked again.",
        )
    return CheckResult(
        "Resources",
        True,
        f"{len(required)} accessible resources; fonts, license, SVG and QSS verified",
    )


def version_tuple(value: str) -> tuple[int, ...]:
    return tuple(int(component) for component in re.findall(r"\d+", value))


def check_gui_platform() -> CheckResult:
    system, machine = platform.system(), platform.machine().lower()
    detail = f"{system} {platform.release()} ({machine})"
    if system == "Windows":
        if machine not in ("amd64", "x86_64"):
            return CheckResult("GUI platform", False, f"{detail}. Windows x86-64 is required.")
        windows_version = version_tuple(platform.version())
        if len(windows_version) < 3 or windows_version < (10, 0, 17763):
            return CheckResult(
                "GUI platform", False, f"{detail}. Windows 10 1809 or later is required."
            )
    elif system == "Darwin":
        mac_version = platform.mac_ver()[0]
        if machine not in ("x86_64", "arm64") or version_tuple(mac_version) < (13,):
            return CheckResult(
                "GUI platform", False, f"{detail}. macOS 13+ Intel or Apple Silicon is required."
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
                "GUI platform",
                False,
                f"{detail}; libc={libc or 'unknown'} {libc_version}. "
                "GNU/Linux x86-64 with glibc 2.34+ is required. See docs/environment.md.",
            )
        detail += f"; glibc {libc_version}"
    else:
        return CheckResult(
            "GUI platform",
            False,
            f"{detail}. The initial matrix covers Windows, macOS and GNU/Linux.",
        )
    return CheckResult("GUI platform", True, detail)


def qt_failure_help(output: str) -> str:
    lowered = output.lower()
    if "no module named" in lowered:
        return "Install Qt with uv sync --locked --group dev --extra gui."
    if any(
        fragment in lowered
        for fragment in (
            "could not connect to display",
            "failed to create wl_display",
            "xdg_runtime_dir",
        )
    ):
        return (
            "Check DISPLAY or WAYLAND_DISPLAY/XDG_RUNTIME_DIR and the graphical session. "
            "For CI, use --platform offscreen or xvfb-run with --platform xcb; "
            "offscreen does not validate the actual desktop."
        )
    if platform.system() == "Linux":
        return (
            "Check the plugin libraries and graphical session; "
            "see docs/environment.md. "
            "If libxcb-cursor.so.0 is missing: Debian/Ubuntu: sudo apt install libxcb-cursor0; "
            "Arch: sudo pacman -S --needed xcb-util-cursor. "
            "If another .so is missing, install the system package specified in that documentation."
        )
    return (
        "Check the minimum system requirements and desktop. Reinstall dependencies with "
        "uv sync --locked --group dev --extra gui; see docs/environment.md."
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
            f"Qt exceeded the timeout of {timeout:g} s; the subprocess has been stopped. "
            f"{output[-4000:]} {qt_failure_help(output)}",
        )
    except OSError as exc:
        return CheckResult("Qt/Fusion", False, f"Could not start the Qt subprocess: {exc}")
    if result.returncode != 0:
        cause = f"code {result.returncode}"
        if result.returncode < 0:
            try:
                cause = f"signal {signal.Signals(-result.returncode).name}"
            except ValueError:
                cause = f"signal {-result.returncode}"
        output = (result.stderr or result.stdout).strip()
        return CheckResult(
            "Qt/Fusion",
            False,
            f"The Qt subprocess exited with {cause}. {output[-4000:]} {qt_failure_help(output)}",
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
            raise ValueError("The report contains incorrect types.")
        if style.lower() != "fusion" or report.get("events") is not True:
            raise ValueError("Fusion or the event loop was not verified.")
        if any(
            report.get(key) is not True
            for key in (
                "imported",
                "edited",
                "tags_written",
                "nfo_written",
                "cover_written",
                "albums_viewed",
                "artists_viewed",
            )
        ):
            raise ValueError(
                "Import and editing were not verified, "
                "including audio writes, artwork, NFO and album and artist views."
            )
    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        return CheckResult("Qt/Fusion", False, f"The subprocess did not confirm the Qt test: {exc}")
    scope = (
        "Headless test; does not confirm the actual desktop."
        if backend in ("offscreen", "minimal")
        else "Graphical backend window and event loop verified."
    )
    return CheckResult(
        "Qt/Fusion",
        True,
        f"Qt {qt_version}, Fusion, backend {backend}; "
        "import, editing, tags, artwork, NFO and album and artist views verified. "
        f"{scope}",
    )


def positive_timeout(value: str) -> float:
    timeout = float(value)
    if not 0 < timeout <= 300:
        raise argparse.ArgumentTypeError("The timeout must be between 0 and 300 seconds.")
    return timeout


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--core", action="store_true", help="Check the core only (default).")
    mode.add_argument("--gui", action="store_true", help="Also check the Qt GUI.")
    parser.add_argument("--platform", choices=("offscreen", "xcb", "wayland"))
    parser.add_argument("--qt-timeout", type=positive_timeout, default=15.0, metavar="SECONDS")
    args = parser.parse_args(argv)
    if args.platform and not args.gui:
        parser.error("--platform requires --gui.")
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
    print(f"Diagnostics: {'GUI' if args.gui else 'core'}: {failures} error(s).")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
