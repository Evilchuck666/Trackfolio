# Build on the target OS: uv run --locked --extra gui --group build python scripts/build.py
from pathlib import Path
import importlib
import hashlib
import json

from PyInstaller.utils.hooks import collect_data_files, collect_submodules, copy_metadata

ROOT = Path(SPECPATH)

# Fail before building if the interpreter or packaged assets are incomplete.
for module in (
    "PySide6.QtWidgets", "PySide6.QtSvg", "PySide6.QtTest",
    "sqlalchemy", "alembic", "mutagen.flac", "mutagen.mp3", "platformdirs",
):
    importlib.import_module(module)
resources = ROOT / "src" / "trackfolio" / "resources"
for name, digest in json.loads((resources / "manifest.json").read_text(encoding="utf-8"))["sha256"].items():
    if hashlib.sha256((resources / name).read_bytes()).hexdigest() != digest:
        raise SystemExit(f"Resource hash mismatch: {name}. Update manifest.json before building.")

# Alembic discovers env.py and revision scripts from the filesystem at runtime.
datas = collect_data_files(
    "trackfolio", include_py_files=True,
    includes=["resources/**", "infrastructure/migrations/**"],
)
datas += [(str(ROOT / "LICENSE"), "licenses/Trackfolio")]
for distribution in ("SQLAlchemy", "alembic", "mutagen", "platformdirs", "PySide6",
                     "PySide6-Essentials", "PySide6-Addons", "shiboken6"):
    datas += copy_metadata(distribution)

analysis = Analysis(
    [str(ROOT / "scripts" / "frozen_entry.py")],
    pathex=[str(ROOT / "src")],
    datas=datas,
    binaries=[],
    hiddenimports=[
        "trackfolio.infrastructure.migrations.initial_schema",
        *collect_submodules("alembic.ddl"),
        *collect_submodules("sqlalchemy.dialects.sqlite"),
    ],
    excludes=["tkinter", "PyQt5", "PyQt6", "PySide2"],
    noarchive=False,
)
pyz = PYZ(analysis.pure)
# No COLLECT or BUNDLE: the result is one native executable, including on macOS.
exe = EXE(
    pyz, analysis.scripts, analysis.binaries, analysis.datas, [],
    name="Trackfolio", debug=False, strip=False, upx=False, console=False,
    runtime_tmpdir=None,
)
