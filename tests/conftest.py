"""Load maintenance scripts independently of pytest's import path or cwd."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


def load_script(name):
    module_name = f"trackfolio_maintenance_{name}"
    path = Path(__file__).resolve().parents[1] / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="session")
def bootstrap():
    return load_script("bootstrap")


@pytest.fixture(scope="session")
def doctor():
    return load_script("doctor")


@pytest.fixture
def configured_root(tmp_path):
    root = tmp_path / "project with spaces"
    root.mkdir()
    (root / "pyproject.toml").write_text(
        '[tool.uv]\nrequired-version = "==0.12.10"\n', encoding="utf-8"
    )
    (root / ".python-version").write_text("3.13.15\n", encoding="utf-8")
    (root / "uv.lock").write_text(
        "version = 1\n"
        '[[package]]\nname = "sqlalchemy"\nversion = "2.0.0"\n'
        '[[package]]\nname = "alembic"\nversion = "1.0.0"\n'
        '[[package]]\nname = "mutagen"\nversion = "1.0.0"\n'
        '[[package]]\nname = "platformdirs"\nversion = "1.0.0"\n',
        encoding="utf-8",
    )
    return root
