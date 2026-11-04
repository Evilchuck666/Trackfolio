"""Validate distribution contents and fail closed on incomplete binary probes."""

import hashlib
import importlib.util
import json
import os
import stat
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path

import pytest

from trackfolio import bundle_probe, launcher


@pytest.fixture
def builder():
    path = Path(__file__).resolve().parents[1] / "scripts" / "build.py"
    spec = importlib.util.spec_from_file_location("standalone_build", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("system", ["linux", "windows", "macos"])
def test_archive_contains_executable_license_and_correct_checksum(builder, tmp_path, system):
    binary = tmp_path / ("Trackfolio.exe" if system == "windows" else "Trackfolio")
    binary.write_bytes(b"binary contents")
    binary.chmod(0o755)
    archive = builder.archive(binary, system, "x64")
    if system == "linux":
        with tarfile.open(archive) as bundle:
            assert set(bundle.getnames()) == {binary.name, "LICENSE"}
            assert bundle.extractfile(binary.name).read() == binary.read_bytes()
            mode = bundle.getmember(binary.name).mode
            assert mode == stat.S_IMODE(binary.stat().st_mode)
            # Windows chmod does not set POSIX executable bits. The archive
            # preserves host permissions; real Linux builds run on Linux.
            if os.name != "nt":
                assert mode & 0o111
    else:
        with zipfile.ZipFile(archive) as bundle:
            assert set(bundle.namelist()) == {binary.name, "LICENSE"}
            assert bundle.read(binary.name) == binary.read_bytes()
    checksum = archive.with_name(archive.name + ".sha256").read_text()
    assert checksum == f"{hashlib.sha256(archive.read_bytes()).hexdigest()}  {archive.name}\n"


@pytest.mark.parametrize("failure", [None, "missing_report", "incomplete", "wrong_backend", "exit"])
def test_verify_isolates_binary_and_requires_full_success(builder, tmp_path, monkeypatch, failure):
    binary = tmp_path / "Trackfolio"
    binary.write_bytes(b"standalone")
    monkeypatch.setenv("PYTHONPATH", "must-not-leak")

    def run(command, **kwargs):
        copied = Path(command[0])
        assert copied.parent != binary.parent
        assert copied.read_bytes() == binary.read_bytes()
        assert kwargs["cwd"] == copied.parent
        assert "PYTHONPATH" not in kwargs["env"]
        if os.name != "nt":
            assert kwargs["env"]["PATH"] == ""
        report = dict.fromkeys(builder.REQUIRED_CHECKS, True)
        report.update(style="fusion", platform="offscreen")
        if failure == "incomplete":
            del report["nfo_written"]
        if failure == "wrong_backend":
            report["platform"] = "xcb"
        if failure != "missing_report":
            Path(command[3]).write_text(json.dumps(report), encoding="utf-8")
        return subprocess.CompletedProcess(command, 1 if failure == "exit" else 0, "", "")

    monkeypatch.setattr(builder.subprocess, "run", run)
    if failure:
        with pytest.raises(RuntimeError):
            builder.verify(binary)
    else:
        builder.verify(binary)


def test_smoke_failure_is_reported_without_console(tmp_path, monkeypatch):
    def missing_resources(package):
        raise FileNotFoundError("missing packaged assets")

    monkeypatch.setattr(bundle_probe, "files", missing_resources)
    report = tmp_path / "report.json"
    assert bundle_probe.main(["--smoke-test", "--report", str(report)]) == 1
    assert "missing packaged assets" in json.loads(report.read_text())["error"]


def test_launcher_dispatches_smoke_test_without_starting_normal_gui(monkeypatch):
    args = ["--smoke-test", "--report", "report.json"]
    received = []
    monkeypatch.setattr(sys, "argv", ["Trackfolio", *args])
    monkeypatch.setattr(bundle_probe, "main", lambda argv: received.append(argv) or 7)
    assert launcher.main() == 7
    assert received == [args]
