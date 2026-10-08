"""Failures must stop bootstrap before changing later parts of the environment."""

from __future__ import annotations

import subprocess

import pytest


@pytest.mark.parametrize("version", ["0.11.99", "0.12.0", "0.12.9", "0.13.0", "0.13.1", "1.0.0"])
def test_wrong_uv_version_stops_before_install(
    bootstrap, configured_root, monkeypatch, capsys, version
):
    monkeypatch.setattr(bootstrap, "PROJECT_ROOT", configured_root)
    monkeypatch.setattr(bootstrap.shutil, "which", lambda _: "uv")
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, f"uv {version}\n", "")

    monkeypatch.setattr(bootstrap.subprocess, "run", run)
    assert bootstrap.main(["--core"]) != 0
    assert calls == [["uv", "--version"]]
    error = capsys.readouterr().err
    assert "requiere uv >=0.12.10,<0.13" in error
    assert f"se encontró {version}" in error
    assert "https://astral.sh/uv/0.12.10/install.sh" in error


@pytest.mark.parametrize("version", ["0.12.10", "0.12.11", "0.12.23", "0.12.100", "0.12.999"])
def test_compatible_uv_version_runs_bootstrap(bootstrap, configured_root, monkeypatch, version):
    monkeypatch.setattr(bootstrap, "PROJECT_ROOT", configured_root)
    monkeypatch.setattr(bootstrap.shutil, "which", lambda _: "uv")
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        output = f"uv {version} (build metadata)\n" if command[1] == "--version" else ""
        return subprocess.CompletedProcess(command, 0, output, "")

    monkeypatch.setattr(bootstrap.subprocess, "run", run)
    assert bootstrap.main(["--core"]) == 0
    assert [command[1] for command in calls] == ["--version", "python", "sync", "run"]


@pytest.mark.parametrize(
    "requirement",
    [">=0.12.10,<0.13", ">=0.12.10,<0.13.0", ">=0.12.10, <0.13", ">=0.12.20,<0.13"],
)
def test_configuration_preserves_uv_range(bootstrap, configured_root, requirement):
    (configured_root / "pyproject.toml").write_text(
        f'[tool.uv]\nrequired-version = "{requirement}"\n', encoding="utf-8"
    )
    assert bootstrap.configuration(configured_root) == (requirement, "3.13.15")


@pytest.mark.parametrize(
    "requirement",
    [
        '""',
        '"==0.12.10"',
        '">=0.12.10"',
        '">=0.12.10,<=0.13"',
        '">=0.12.10,<0.12"',
        '">=0.13.0,<0.13.0"',
        '">=0.13.1,<0.13"',
        "12",
    ],
)
def test_invalid_uv_range_stops_before_invoking_uv(
    bootstrap, configured_root, monkeypatch, capsys, requirement
):
    (configured_root / "pyproject.toml").write_text(
        f"[tool.uv]\nrequired-version = {requirement}\n", encoding="utf-8"
    )
    monkeypatch.setattr(bootstrap, "PROJECT_ROOT", configured_root)

    def forbidden(_):
        pytest.fail("uv must not run with an invalid version range")

    monkeypatch.setattr(bootstrap, "check_uv", forbidden)
    assert bootstrap.main([]) != 0
    assert "tool.uv.required-version" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("requirement", "version", "accepted"),
    [
        (">=0.12.20,<0.13", "0.12.23", True),
        (">=0.12.20,<0.13", "0.12.10", False),
        (">=0.12.10,<0.12.24", "0.12.23", True),
        (">=0.12.10,<0.12.24", "0.12.24", False),
        (">=0.12.10,<0.13.0", "0.13.0", False),
    ],
)
def test_uv_check_uses_configured_bounds(bootstrap, monkeypatch, requirement, version, accepted):
    monkeypatch.setattr(bootstrap.shutil, "which", lambda _: "uv")
    monkeypatch.setattr(
        bootstrap.subprocess,
        "run",
        lambda command, **kwargs: subprocess.CompletedProcess(command, 0, f"uv {version}\n", ""),
    )
    if accepted:
        assert bootstrap.check_uv(requirement) == "uv"
    else:
        with pytest.raises(bootstrap.BootstrapError, match="requiere uv"):
            bootstrap.check_uv(requirement)


@pytest.mark.parametrize("output", ["uv unknown\n", "uv 0.12\n", "uv 0.12.23rc1\n"])
def test_unrecognized_uv_version_is_rejected(bootstrap, monkeypatch, output):
    monkeypatch.setattr(bootstrap.shutil, "which", lambda _: "uv")
    monkeypatch.setattr(
        bootstrap.subprocess,
        "run",
        lambda command, **kwargs: subprocess.CompletedProcess(command, 0, output, ""),
    )
    with pytest.raises(bootstrap.BootstrapError, match="respuesta desconocida"):
        bootstrap.check_uv(">=0.12.10,<0.13")


def test_missing_lock_fails_without_invoking_uv(bootstrap, configured_root, monkeypatch, capsys):
    (configured_root / "uv.lock").unlink()
    monkeypatch.setattr(bootstrap, "PROJECT_ROOT", configured_root)

    def forbidden(_):
        pytest.fail("uv must not run without the checked-in lock")

    monkeypatch.setattr(bootstrap, "check_uv", forbidden)
    assert bootstrap.main([]) != 0
    assert "uv.lock" in capsys.readouterr().err


def test_missing_uv_provides_minimum_version_install_instructions(bootstrap, monkeypatch):
    monkeypatch.setattr(bootstrap.shutil, "which", lambda _: None)
    with pytest.raises(bootstrap.BootstrapError) as failure:
        bootstrap.check_uv(">=0.12.10,<0.13")
    assert "Se requiere uv >=0.12.10,<0.13" in str(failure.value)
    assert "https://astral.sh/uv/0.12.10/install.sh" in str(failure.value)
    assert "install.ps1" in str(failure.value)


def test_outdated_lock_error_is_propagated_and_doctor_is_not_started(
    bootstrap, configured_root, monkeypatch, capsys
):
    monkeypatch.setattr(bootstrap, "PROJECT_ROOT", configured_root)
    monkeypatch.setattr(bootstrap, "check_uv", lambda _: "uv")
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        return subprocess.CompletedProcess(command, 42 if command[1] == "sync" else 0)

    monkeypatch.setattr(bootstrap.subprocess, "run", run)
    assert bootstrap.main(["--gui", "--platform", "offscreen"]) == 42
    assert [command[1] for command in calls] == ["python", "sync"]
    assert "--locked" in calls[-1]
    assert "uv lock" in capsys.readouterr().err


def test_bootstrap_works_from_another_cwd_and_forwards_gui_selection(
    bootstrap, configured_root, monkeypatch, tmp_path
):
    monkeypatch.setattr(bootstrap, "PROJECT_ROOT", configured_root)
    monkeypatch.setattr(bootstrap, "check_uv", lambda _: "uv with spaces")
    monkeypatch.chdir(tmp_path)
    calls = []

    def run(command, **kwargs):
        assert isinstance(command, list)
        assert kwargs["cwd"] == configured_root
        assert kwargs.get("shell", False) is False
        calls.append(command)
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(bootstrap.subprocess, "run", run)
    assert bootstrap.main(["--gui", "--platform", "offscreen", "--qt-timeout", "2"]) == 0
    assert len(calls) == 3
    assert calls[0] == ["uv with spaces", "python", "install", "3.13.15"]
    assert calls[-1][-5:] == ["--gui", "--qt-timeout", "2.0", "--platform", "offscreen"]
    assert all("--locked" in command for command in calls[1:])


@pytest.mark.parametrize("timeout", ["0", "-1", "301", "nan", "inf"])
def test_invalid_timeout_is_rejected_before_any_work(bootstrap, timeout):
    with pytest.raises(SystemExit) as failure:
        bootstrap.parse_args(["--gui", "--qt-timeout", timeout])
    assert failure.value.code != 0
