"""Build and verify a native onefile executable, then archive it for distribution."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import tarfile
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REQUIRED_CHECKS = (
    "frozen",
    "resources_verified",
    "events",
    "imported",
    "edited",
    "tags_written",
    "nfo_written",
    "cover_written",
    "albums_viewed",
    "artists_viewed",
)


def target() -> tuple[str, str]:
    system = {"Linux": "linux", "Windows": "windows", "Darwin": "macos"}.get(platform.system())
    architecture = {"x86_64": "x64", "amd64": "x64", "arm64": "arm64"}.get(
        platform.machine().lower()
    )
    if system is None or architecture is None or (architecture == "arm64" and system != "macos"):
        raise RuntimeError("Supported targets: Linux/Windows x64 and macOS x64/arm64.")
    return system, architecture


def verify(executable: Path, qt_platform: str = "offscreen") -> None:
    """Run only a copied executable, without checkout paths or Python on PATH."""
    executable = executable.resolve(strict=True)
    with tempfile.TemporaryDirectory(prefix="Trackfolio standalone Ω ") as temporary:
        directory = Path(temporary)
        copied = directory / executable.name
        shutil.copy2(executable, copied)
        environment = os.environ.copy()
        for key in (
            "PYTHONHOME",
            "PYTHONPATH",
            "VIRTUAL_ENV",
            "QT_PLUGIN_PATH",
            "QT_QPA_PLATFORM_PLUGIN_PATH",
            "LD_LIBRARY_PATH",
            "DYLD_LIBRARY_PATH",
        ):
            environment.pop(key, None)
        environment["QT_QPA_PLATFORM"] = qt_platform
        environment["PATH"] = ""
        if os.name == "nt":
            windows = Path(environment["SYSTEMROOT"])
            environment["PATH"] = os.pathsep.join((str(windows / "System32"), str(windows)))
        report_path = directory / "report.json"
        completed = subprocess.run(
            [str(copied), "--smoke-test", "--report", str(report_path), "--platform", qt_platform],
            cwd=directory,
            env=environment,
            check=False,
            timeout=120,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if completed.returncode != 0 or not report_path.is_file():
            detail = report_path.read_text(encoding="utf-8") if report_path.is_file() else ""
            raise RuntimeError(
                f"Standalone verification failed ({completed.returncode}).\n"
                f"{completed.stdout}\n{completed.stderr}\n{detail}"
            )
        report = json.loads(report_path.read_text(encoding="utf-8"))
        if any(report.get(key) is not True for key in REQUIRED_CHECKS):
            raise RuntimeError(f"Incomplete standalone report: {report}")
        if report.get("style") != "fusion" or report.get("platform") != qt_platform:
            raise RuntimeError(f"Incorrect standalone Qt backend/style: {report}")
        print(f"Standalone verification passed ({qt_platform}): {executable.name}")


def archive(executable: Path, system: str, architecture: str) -> Path:
    """Write a complete platform archive atomically, retaining executable permissions."""
    suffix = ".tar.gz" if system == "linux" else ".zip"
    destination = executable.parent / f"Trackfolio-{system}-{architecture}{suffix}"
    with tempfile.TemporaryDirectory(dir=executable.parent) as temporary:
        staged = Path(temporary) / destination.name
        if system == "linux":
            with tarfile.open(staged, "w:gz") as bundle:
                bundle.add(executable, arcname=executable.name)
                bundle.add(ROOT / "LICENSE", arcname="LICENSE")
        else:
            with zipfile.ZipFile(staged, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
                bundle.write(executable, arcname=executable.name)
                bundle.write(ROOT / "LICENSE", arcname="LICENSE")
        staged.replace(destination)
    digest = hashlib.sha256(destination.read_bytes()).hexdigest()
    destination.with_name(destination.name + ".sha256").write_text(
        f"{digest}  {destination.name}\n", encoding="utf-8"
    )
    return destination


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verify-only", type=Path, help="Verify an existing executable.")
    parser.add_argument("--platform", default="offscreen", help="Qt backend for verification.")
    args = parser.parse_args(argv)
    if args.verify_only is not None:
        verify(args.verify_only, args.platform)
        return 0
    system, architecture = target()
    subprocess.run(
        [sys.executable, "-m", "PyInstaller", "--clean", "--noconfirm", "Trackfolio.spec"],
        cwd=ROOT,
        check=True,
    )
    executable = ROOT / "dist" / ("Trackfolio.exe" if system == "windows" else "Trackfolio")
    verify(executable, args.platform)
    package = archive(executable, system, architecture)
    print(f"Executable: {executable}\nVerified archive: {package}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
