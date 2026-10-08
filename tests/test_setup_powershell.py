"""Test argument forwarding using real PowerShell and a fake uv, without downloads."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
POWERSHELL = (
    os.environ.get("TRACKFOLIO_TEST_PWSH") or shutil.which("powershell") or shutil.which("pwsh")
)


@pytest.fixture
def powershell_launcher(tmp_path):
    if not POWERSHELL:
        pytest.skip("PowerShell is not installed")
    root = tmp_path / "project with spaces ñ"
    (root / "scripts").mkdir(parents=True)
    shutil.copyfile(ROOT / "setup.ps1", root / "setup.ps1")
    shutil.copyfile(ROOT / "pyproject.toml", root / "pyproject.toml")
    (root / ".python-version").write_text("3.13.15\n", encoding="utf-8")
    (root / "uv.lock").write_text("lock exists\n", encoding="utf-8")
    (root / "scripts/setup.py").write_text("pass\n", encoding="utf-8")
    helper = tmp_path / "fake_uv.py"
    helper.write_text(
        "import json, os, pathlib, sys\n"
        "if sys.argv[1] == 'version':\n"
        "    print('0.1.0')\n"
        "    sys.exit(0)\n"
        "pathlib.Path(os.environ['TEST_UV_LOG']).write_text(\n"
        "    json.dumps(sys.argv[1:], ensure_ascii=False), encoding='utf-8')\n"
        "sys.exit(int(os.environ.get('TEST_UV_EXIT', '0')))\n",
        encoding="utf-8",
    )
    binaries = tmp_path / "bin"
    binaries.mkdir()
    if os.name == "nt":
        executable = binaries / "uv.cmd"
        executable.write_text(
            '@echo off\n"%TEST_PYTHON%" "%TEST_UV_SCRIPT%" %*\nexit /b %errorlevel%\n',
            encoding="ascii",
        )
    else:
        executable = binaries / "uv"
        executable.write_text(
            '#!/bin/sh\nexec "$TEST_PYTHON" "$TEST_UV_SCRIPT" "$@"\n', encoding="utf-8"
        )
        executable.chmod(0o755)
    log = tmp_path / "uv.json"
    environment = dict(
        os.environ,
        PATH=str(binaries) + os.pathsep + os.environ.get("PATH", ""),
        TEST_PYTHON=sys.executable,
        TEST_UV_SCRIPT=str(helper),
        TEST_UV_LOG=str(log),
    )
    return root, executable, environment, log


def launch(fixture, *arguments):
    root, _, environment, _ = fixture
    return subprocess.run(
        [
            POWERSHELL,
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(root / "setup.ps1"),
            *arguments,
        ],
        cwd=root.parent,
        env=environment,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        timeout=30,
    )


def test_powershell_help_does_not_invoke_uv(powershell_launcher):
    root, _, _, log = powershell_launcher
    result = launch(powershell_launcher, "--help")
    assert result.returncode == 0, result.stderr
    assert "--skip-editor" in result.stdout
    assert not log.exists()
    assert not (root / ".tools").exists()


def test_powershell_reuses_uv_and_preserves_setup_arguments(powershell_launcher):
    root, executable, _, log = powershell_launcher
    result = launch(powershell_launcher, "--core", "--skip-editor", "--non-interactive")
    assert result.returncode == 0, result.stderr
    arguments = json.loads(log.read_text(encoding="utf-8"))
    assert arguments[:5] == ["run", "--no-project", "--managed-python", "--python", "3.13.15"]
    assert arguments[5:9] == ["python", "-m", "scripts.setup", "--uv"]
    assert Path(arguments[9]) == executable
    assert arguments[10:] == ["--core", "--skip-editor", "--non-interactive"]
    assert not (root / ".tools").exists()


def test_powershell_run_uv_preserves_paths_and_exit_code(powershell_launcher):
    _, _, environment, log = powershell_launcher
    environment["TEST_UV_EXIT"] = "19"
    arguments = ["run", "--locked", "trackfolio", "--database", "catalog # 1.sqlite3"]
    result = launch(powershell_launcher, "--run-uv", *arguments)
    assert result.returncode == 19, result.stderr
    assert json.loads(log.read_text(encoding="utf-8")) == arguments


def test_powershell_invalid_range_stops_before_invoking_uv(powershell_launcher):
    root, _, _, log = powershell_launcher
    (root / "pyproject.toml").write_text(
        '[tool.uv]\nrequired-version=">=0.13.0,<0.13"\n', encoding="utf-8"
    )
    result = launch(powershell_launcher, "--non-interactive")
    assert result.returncode == 1
    assert not log.exists()
    assert not (root / ".tools").exists()
