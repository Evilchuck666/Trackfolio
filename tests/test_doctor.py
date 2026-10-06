"""Exercise failure reporting and real subprocess isolation without requiring Qt."""

from __future__ import annotations

import json
import signal
import subprocess

import pytest


def test_dependency_version_drift_is_an_error(doctor, configured_root, monkeypatch):
    versions = {"SQLAlchemy": "999.0", "alembic": "1.0.0", "mutagen": "1.0.0"}
    monkeypatch.setattr(
        doctor.importlib.metadata, "version", lambda name: versions.get(name, "1.0.0")
    )
    results = doctor.check_versions(configured_root, gui=False)
    failed = [result for result in results if not result.ok]
    assert len(failed) == 1
    assert failed[0].name == "SQLAlchemy"
    assert "999.0" in failed[0].detail and "2.0.0" in failed[0].detail
    assert "uv sync --locked" in failed[0].detail


def test_core_does_not_require_gui_packages(doctor, configured_root, monkeypatch):
    checked = []

    def installed(name):
        checked.append(name)
        return "2.0.0" if name == "SQLAlchemy" else "1.0.0"

    monkeypatch.setattr(doctor.importlib.metadata, "version", installed)
    assert all(result.ok for result in doctor.check_versions(configured_root, gui=False))
    assert not any("pyside" in name.lower() or "shiboken" in name.lower() for name in checked)


def test_missing_distribution_is_an_error_with_repair_command(doctor, configured_root, monkeypatch):
    def missing(name):
        raise doctor.importlib.metadata.PackageNotFoundError(name)

    monkeypatch.setattr(doctor.importlib.metadata, "version", missing)
    results = doctor.check_versions(configured_root, gui=False)
    assert all(not result.ok for result in results)
    assert all("uv sync --locked" in result.detail for result in results)


def test_invalid_lock_is_an_error(doctor, configured_root):
    (configured_root / "uv.lock").write_text("not valid TOML", encoding="utf-8")
    results = doctor.check_versions(configured_root, gui=False)
    assert len(results) == 1 and not results[0].ok
    assert results[0].name == "uv.lock"


def test_structurally_invalid_lock_is_an_actionable_error(doctor, configured_root):
    (configured_root / "uv.lock").write_text('package = ["invalid package"]', encoding="utf-8")
    results = doctor.check_versions(configured_root, gui=False)
    assert len(results) == 1 and not results[0].ok
    assert "tabla TOML" in results[0].detail
    assert "Recupera uv.lock" in results[0].detail


def test_qt_abort_is_reported_without_aborting_doctor(doctor, monkeypatch):
    def abort(command, **kwargs):
        assert command[0] == doctor.sys.executable
        return subprocess.CompletedProcess(
            command, -signal.SIGABRT, "", "xcb plugin: libxcb-cursor.so.0 missing"
        )

    monkeypatch.setattr(doctor.subprocess, "run", abort)
    result = doctor.check_qt("xcb", timeout=2)
    assert not result.ok
    assert "SIGABRT" in result.detail
    assert "libxcb-cursor.so.0" in result.detail


def test_hung_qt_child_is_killed_and_reported(doctor, monkeypatch):
    monkeypatch.setattr(doctor, "QT_PROBE", "import time; time.sleep(30)")
    result = doctor.check_qt(None, timeout=0.2)
    assert not result.ok
    assert "timeout" in result.detail
    assert "detenido el subproceso" in result.detail


def test_child_success_without_qt_report_is_not_accepted(doctor, monkeypatch):
    monkeypatch.setattr(doctor, "QT_PROBE", "print('not a Qt confirmation')")
    result = doctor.check_qt(None, timeout=5)
    assert not result.ok
    assert "no confirmó" in result.detail


@pytest.mark.parametrize("backend", ["offscreen", "minimal"])
def test_headless_qt_success_does_not_claim_desktop_validation(doctor, monkeypatch, backend):
    report = {"platform": backend, "style": "fusion", "qt_version": "6.11.2", "events": True}
    output = doctor.QT_PROBE_PREFIX + json.dumps(report)

    def run(command, **kwargs):
        return subprocess.CompletedProcess(command, 0, output, "")

    monkeypatch.setattr(doctor.subprocess, "run", run)
    result = doctor.check_qt(backend, timeout=2)
    assert result.ok
    assert "no confirma el escritorio real" in result.detail


def test_sqlite_persists_unicode_through_sqlalchemy_and_removes_temp_file(
    doctor, monkeypatch, tmp_path
):
    monkeypatch.setattr(doctor.tempfile, "tempdir", str(tmp_path))
    result = doctor.check_sqlite()
    assert result.ok, result.detail
    assert list(tmp_path.iterdir()) == []


def test_old_linux_glibc_is_rejected_for_gui(doctor, monkeypatch):
    monkeypatch.setattr(doctor.platform, "system", lambda: "Linux")
    monkeypatch.setattr(doctor.platform, "machine", lambda: "x86_64")
    monkeypatch.setattr(doctor.platform, "libc_ver", lambda: ("glibc", "2.31"))
    result = doctor.check_gui_platform()
    assert not result.ok
    assert "glibc 2.34+" in result.detail


def test_doctor_returns_nonzero_when_a_required_check_fails(doctor, monkeypatch, capsys):
    monkeypatch.setattr(
        doctor, "check_python", lambda _: doctor.CheckResult("Python", False, "Wrong version")
    )
    monkeypatch.setattr(doctor, "check_versions", lambda *args: [])
    monkeypatch.setattr(doctor, "check_imports", lambda: [])
    monkeypatch.setattr(doctor, "check_sqlite", lambda: doctor.CheckResult("SQLite", True, "OK"))
    monkeypatch.setattr(
        doctor, "check_resources", lambda: doctor.CheckResult("Recursos", True, "OK")
    )
    assert doctor.main(["--core"]) != 0
    assert "1 error(es)" in capsys.readouterr().out
