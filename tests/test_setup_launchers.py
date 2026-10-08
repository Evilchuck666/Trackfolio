"""Exercise the Unix entry point without a real uv, Python, downloads or system installs."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
BASH = shutil.which("bash")


def fake_uv(path, *, compatible=True):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "#!/bin/sh\n"
        'case "$1" in\n'
        f"  version) exit {0 if compatible else 2} ;;\n"
        '  *) printf \'%s\\n\' "$@" > "$TEST_UV_LOG"; exit "${TEST_UV_EXIT:-0}" ;;\n'
        "esac\n",
        encoding="utf-8",
    )
    path.chmod(0o755)


@pytest.fixture
def launcher(tmp_path):
    if os.name == "nt" or not BASH:
        pytest.skip("Unix launcher needs Bash")
    root = tmp_path / "project with spaces ñ"
    (root / "scripts").mkdir(parents=True)
    shutil.copyfile(ROOT / "setup.sh", root / "setup.sh")
    shutil.copyfile(ROOT / "pyproject.toml", root / "pyproject.toml")
    (root / ".python-version").write_text("3.13.15\n", encoding="utf-8")
    (root / "uv.lock").write_text("lock exists\n", encoding="utf-8")
    (root / "scripts/setup.py").write_text("pass\n", encoding="utf-8")
    binaries = tmp_path / "bin"
    binaries.mkdir()
    for name in ["awk", "dirname", "mkdir", "mktemp", "rm", "sh", "cp", "chmod", "cat"]:
        executable = shutil.which(name)
        if executable is None:
            pytest.skip(f"Test needs {name}")
        (binaries / name).symlink_to(executable)
    home = tmp_path / "home"
    home.mkdir()
    (home / ".profile").write_text("User profile\n", encoding="utf-8")
    log = tmp_path / "uv.log"
    environment = dict(os.environ, PATH=str(binaries), HOME=str(home), TEST_UV_LOG=str(log))
    return root, binaries, environment, log


def launch(launcher, *arguments):
    root, _, environment, _ = launcher
    return subprocess.run(
        [BASH, str(root / "setup.sh"), *arguments],
        cwd=root.parent,
        env=environment,
        text=True,
        encoding="utf-8",
        capture_output=True,
        timeout=30,
    )


def fake_downloader(launcher, tmp_path):
    root, binaries, environment, _ = launcher
    source = tmp_path / "source-uv"
    fake_uv(source)
    installer = tmp_path / "installer.sh"
    installer.write_text(
        "#!/bin/sh\nset -eu\n"
        '[ "$UV_NO_MODIFY_PATH" = 1 ]\n'
        'printf \'%s\\n\' "$UV_UNMANAGED_INSTALL" >> "$TEST_INSTALL_LOG"\n'
        'cp "$TEST_UV_SOURCE" "$UV_UNMANAGED_INSTALL/uv"\n'
        'chmod +x "$UV_UNMANAGED_INSTALL/uv"\n',
        encoding="utf-8",
    )
    curl = binaries / "curl"
    curl.write_text(
        "#!/bin/sh\nset -eu\n"
        'if [ "${TEST_DOWNLOAD_FAILURE:-0}" != 0 ]; then exit "$TEST_DOWNLOAD_FAILURE"; fi\n'
        'while [ "$#" -gt 0 ]; do\n'
        '  if [ "$1" = --output ]; then shift; destination="$1"; fi\n'
        "  shift\n"
        "done\n"
        'cp "$TEST_INSTALLER_SOURCE" "$destination"\n',
        encoding="utf-8",
    )
    curl.chmod(0o755)
    environment.update(
        TEST_UV_SOURCE=str(source),
        TEST_INSTALLER_SOURCE=str(installer),
        TEST_INSTALL_LOG=str(tmp_path / "install.log"),
    )
    return root / ".tools/uv/uv"


def test_help_needs_no_uv_or_python_and_writes_nothing(launcher):
    root, _, _, log = launcher
    result = launch(launcher, "--help")
    assert result.returncode == 0, result.stderr
    assert "--skip-editor" in result.stdout
    assert not (root / ".tools").exists()
    assert not log.exists()


def test_installed_uv_is_reused_and_arguments_are_preserved(launcher):
    root, binaries, _, log = launcher
    fake_uv(binaries / "uv")
    result = launch(launcher, "--core", "--skip-editor", "--non-interactive")
    assert result.returncode == 0, result.stderr
    arguments = log.read_text(encoding="utf-8").splitlines()
    assert arguments[:9] == [
        "run",
        "--no-project",
        "--managed-python",
        "--python",
        "3.13.15",
        "python",
        "-m",
        "scripts.setup",
        "--uv",
    ]
    assert arguments[9] == str(binaries / "uv")
    assert arguments[10:] == ["--core", "--skip-editor", "--non-interactive"]
    assert not (root / ".tools").exists()


def test_incompatible_uv_uses_existing_project_uv_without_download(launcher):
    root, binaries, _, log = launcher
    fake_uv(binaries / "uv", compatible=False)
    local = root / ".tools/uv/uv"
    fake_uv(local)
    result = launch(launcher, "--skip-editor")
    assert result.returncode == 0, result.stderr
    assert str(local) in log.read_text(encoding="utf-8").splitlines()


def test_compatible_uv_later_in_path_is_reused(launcher, tmp_path):
    root, binaries, environment, log = launcher
    fake_uv(binaries / "uv", compatible=False)
    second = tmp_path / "other tools/uv"
    fake_uv(second)
    environment["PATH"] += os.pathsep + str(second.parent)
    result = launch(launcher, "--skip-editor")
    assert result.returncode == 0, result.stderr
    assert str(second) in log.read_text(encoding="utf-8").splitlines()
    assert not (root / ".tools").exists()


def test_missing_uv_is_installed_locally_and_setup_is_repeatable(launcher, tmp_path):
    root, _, environment, _ = launcher
    local = fake_downloader(launcher, tmp_path)
    for _ in range(2):
        result = launch(launcher, "--skip-editor", "--non-interactive")
        assert result.returncode == 0, result.stderr
    assert local.is_file()
    assert Path(environment["TEST_INSTALL_LOG"]).read_text().splitlines() == [str(local.parent)]
    assert Path(environment["HOME"], ".profile").read_text() == "User profile\n"
    assert sorted(item.name for item in local.parent.iterdir()) == ["uv"]
    assert not (root / ".venv").exists()  # The fake uv never executes Python.


def test_failed_download_propagates_error_and_cleans_own_temporary_file(launcher, tmp_path):
    root, _, environment, _ = launcher
    local = fake_downloader(launcher, tmp_path)
    environment["TEST_DOWNLOAD_FAILURE"] = "7"
    result = launch(launcher, "--non-interactive")
    assert result.returncode == 7
    assert not local.exists()
    assert list((root / ".tools/uv").iterdir()) == []


def test_run_uv_does_not_prepare_environment_and_preserves_paths(launcher):
    _, binaries, environment, log = launcher
    fake_uv(binaries / "uv")
    environment["TEST_UV_EXIT"] = "19"
    arguments = [
        "run",
        "--locked",
        "--extra",
        "gui",
        "trackfolio",
        "--database",
        "catálogo # 1.sqlite3",
    ]
    result = launch(launcher, "--run-uv", *arguments)
    assert result.returncode == 19
    assert log.read_text(encoding="utf-8").splitlines() == arguments


def test_run_uv_without_compatible_uv_does_not_download(launcher, tmp_path):
    root, _, environment, _ = launcher
    fake_downloader(launcher, tmp_path)
    result = launch(launcher, "--run-uv", "--version")
    assert result.returncode == 1
    assert "Ejecuta primero" in result.stderr
    assert not (root / ".tools").exists()
    assert not Path(environment["TEST_INSTALL_LOG"]).exists()


@pytest.mark.parametrize("required", ["==0.12.10", ">=0.13.0,<0.13", ">=0.12.10,<0.12"])
def test_invalid_range_is_rejected_before_download(launcher, required):
    root, _, _, _ = launcher
    (root / "pyproject.toml").write_text(
        f'[tool.uv]\nrequired-version="{required}"\n', encoding="utf-8"
    )
    result = launch(launcher, "--non-interactive")
    assert result.returncode == 1
    assert not (root / ".tools").exists()


def test_vscode_tasks_use_platform_launchers():
    tasks = json.loads((ROOT / ".vscode/tasks.json").read_text(encoding="utf-8"))["tasks"]
    for task in tasks:
        if task.get("type") != "process":
            continue
        assert task["command"] == "bash"
        assert task["args"][0] == "${workspaceFolder}/setup.sh"
        windows = task["windows"]
        assert windows["command"] == "powershell"
        assert windows["args"][4] == "${workspaceFolder}/setup.ps1"
        assert task["args"][1:] == windows["args"][5:]
