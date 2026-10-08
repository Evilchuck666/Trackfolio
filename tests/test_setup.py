"""Setup must isolate downloads, preserve user data and require system-install consent."""

from __future__ import annotations

import argparse
import io
import json
import stat
import tarfile
from pathlib import Path
from types import SimpleNamespace
from zipfile import ZipFile, ZipInfo

import pytest


def options(**values):
    return argparse.Namespace(
        **{"yes": False, "non_interactive": True, "skip_editor": False, **values}
    )


@pytest.mark.parametrize(
    ("release", "expected"),
    [
        ({"ID": "ubuntu", "ID_LIKE": "debian"}, "debian"),
        ({"ID": "debian"}, "debian"),
        ({"ID": "artix"}, "arch"),
        ({"ID": "manjaro", "ID_LIKE": "arch"}, "arch"),
        ({"ID": "fedora"}, "fedora"),
        ({"ID": "rocky", "ID_LIKE": "rhel fedora"}, "fedora"),
        ({"ID": "unknown"}, None),
    ],
)
def test_linux_distribution_detection(setup, monkeypatch, release, expected):
    monkeypatch.setattr(setup.platform, "freedesktop_os_release", lambda: release)
    assert setup.linux_family() == expected


@pytest.mark.parametrize(
    ("family", "manager"), [("debian", "apt-get"), ("arch", "pacman"), ("fedora", "dnf")]
)
def test_package_installation_commands_are_explicit_and_do_not_upgrade_system(
    setup, monkeypatch, family, manager
):
    monkeypatch.setattr(setup, "sys", SimpleNamespace(platform="linux"))
    monkeypatch.setattr(setup, "linux_family", lambda: family)
    monkeypatch.setattr(setup.os, "geteuid", lambda: 1000, raising=False)
    monkeypatch.setattr(setup.shutil, "which", lambda name: f"/tools/{name}")
    commands = setup.package_commands(["git"])
    assert all(command[0] == "/tools/sudo" for command in commands)
    assert commands[-1][1] == manager
    assert commands[-1][-1] == "git"
    assert not any(
        "upgrade" in argument or "-Syu" in argument for command in commands for argument in command
    )


@pytest.mark.parametrize("platform", ["win32", "darwin"])
def test_package_installation_rejects_non_linux_before_checking_system(
    setup, monkeypatch, platform
):
    monkeypatch.setattr(setup, "sys", SimpleNamespace(platform=platform))
    monkeypatch.setattr(setup, "os", SimpleNamespace())
    monkeypatch.setattr(
        setup, "linux_family", lambda: pytest.fail("Linux-only checks must not run")
    )
    with pytest.raises(setup.SetupError, match="solo se admite en Linux"):
        setup.package_commands(["git"])


def test_noninteractive_does_not_authorize_system_changes(setup, monkeypatch):
    monkeypatch.setattr("builtins.input", lambda _: pytest.fail("No interactive input permitted"))
    assert setup.confirm("Install?", options()) is False
    args = options()
    args.yes = True
    assert setup.confirm("Install?", args) is True


@pytest.mark.parametrize(
    ("environment", "expected"),
    [
        ({}, "offscreen"),
        ({"DISPLAY": ":0", "XDG_SESSION_TYPE": "x11"}, "xcb"),
        ({"WAYLAND_DISPLAY": "wayland-0", "XDG_SESSION_TYPE": "wayland"}, "wayland"),
        ({"DISPLAY": ":0", "WAYLAND_DISPLAY": "wayland-0", "XDG_SESSION_TYPE": "x11"}, "xcb"),
    ],
)
def test_graphical_backend_detection(setup, monkeypatch, environment, expected):
    monkeypatch.setattr(setup.platform, "system", lambda: "Linux")
    for name in ["DISPLAY", "WAYLAND_DISPLAY", "XDG_SESSION_TYPE"]:
        monkeypatch.delenv(name, raising=False)
    for name, value in environment.items():
        monkeypatch.setenv(name, value)
    assert setup.graphical_platform(None) == expected
    assert setup.graphical_platform("offscreen") == "offscreen"


def configure_graphics(setup, monkeypatch):
    monkeypatch.setattr(setup.platform, "system", lambda: "Linux")
    monkeypatch.setattr(setup.doctor, "check_gui_platform", lambda: SimpleNamespace(ok=True))
    monkeypatch.setattr(setup, "linux_family", lambda: "arch")
    monkeypatch.setattr(setup, "package_commands", lambda packages: [["install", *packages]])


def test_missing_graphics_are_not_installed_without_consent(setup, monkeypatch):
    configure_graphics(setup, monkeypatch)
    monkeypatch.setattr(setup, "library_available", lambda name: name != "xcb-cursor")
    monkeypatch.setattr(setup, "run", lambda *_: pytest.fail("No system changes permitted"))
    with pytest.raises(setup.SetupError, match="No se autorizaron"):
        setup.prepare_graphics("xcb", options())


def test_missing_graphics_are_installed_and_checked_again(setup, monkeypatch):
    configure_graphics(setup, monkeypatch)
    installed = []
    monkeypatch.setattr(
        setup, "library_available", lambda name: name != "xcb-cursor" or bool(installed)
    )
    monkeypatch.setattr(setup, "run", installed.append)
    args = options()
    args.yes = True
    setup.prepare_graphics("xcb", args)
    assert installed == [["install", "xcb-util-cursor"]]


def test_available_graphics_never_prompt_or_install(setup, monkeypatch):
    configure_graphics(setup, monkeypatch)
    monkeypatch.setattr(setup, "library_available", lambda _: True)
    monkeypatch.setattr(setup, "confirm", lambda *_: pytest.fail("Nothing needs installing"))
    setup.prepare_graphics("wayland", options())


def test_installed_git_is_reused(setup, monkeypatch):
    monkeypatch.setattr(setup.shutil, "which", lambda _: "/installed/git")
    monkeypatch.setattr(setup, "confirm", lambda *_: pytest.fail("Git is already installed"))
    setup.prepare_git(options())


def test_missing_git_is_optional_when_installation_declined(setup, monkeypatch, capsys):
    monkeypatch.setattr(setup.shutil, "which", lambda _: None)
    monkeypatch.setattr(setup.platform, "system", lambda: "Linux")
    monkeypatch.setattr(setup, "package_commands", lambda packages: [["install", *packages]])
    monkeypatch.setattr(setup, "run", lambda *_: pytest.fail("No consent"))
    setup.prepare_git(options())
    assert "Git no instalado" in capsys.readouterr().out


@pytest.mark.parametrize(
    ("system", "machine", "target"),
    [
        ("Linux", "x86_64", "linux-x64"),
        ("Windows", "AMD64", "win32-x64-archive"),
        ("Darwin", "x86_64", "darwin"),
        ("Darwin", "arm64", "darwin-arm64"),
    ],
)
def test_editor_download_uses_official_platform_url(setup, monkeypatch, system, machine, target):
    monkeypatch.setattr(setup.platform, "system", lambda: system)
    monkeypatch.setattr(setup.platform, "machine", lambda: machine)
    assert (
        setup.editor_download()[0] == f"https://update.code.visualstudio.com/latest/{target}/stable"
    )


def test_existing_editor_is_not_downloaded(setup, monkeypatch):
    editor = Path("installed editor/code")
    monkeypatch.setattr(setup, "find_editor", lambda: editor)
    monkeypatch.setattr(setup, "confirm", lambda *_: pytest.fail("The editor already exists"))
    assert setup.install_editor(options()) == editor


def test_declined_editor_download_creates_no_files(setup, monkeypatch, tmp_path):
    monkeypatch.setattr(setup, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(setup, "find_editor", lambda: None)
    assert setup.install_editor(options()) is None
    assert not (tmp_path / ".tools").exists()


def test_editor_download_is_local_atomic_and_reused(setup, monkeypatch, tmp_path):
    monkeypatch.setattr(setup, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(setup.platform, "system", lambda: "Linux")
    monkeypatch.setattr(setup.platform, "machine", lambda: "x86_64")
    monkeypatch.setattr(setup.shutil, "which", lambda _: None)
    downloads = []

    def download(url, target):
        downloads.append(url)
        with tarfile.open(target, "w:gz") as archive:
            data = b"#!/bin/sh\nexit 0\n"
            member = tarfile.TarInfo("VSCode-linux-x64/bin/code")
            member.size = len(data)
            member.mode = 0o755
            archive.addfile(member, io.BytesIO(data))

    monkeypatch.setattr(setup, "download", download)
    args = options()
    args.yes = True
    editor = setup.install_editor(args)
    assert editor == tmp_path / ".tools/vscode/bin/code"
    assert editor.is_file()
    assert setup.install_editor(args) == editor
    assert len(downloads) == 1
    assert sorted(item.name for item in (tmp_path / ".tools").iterdir()) == ["vscode"]


def test_unknown_editor_directory_is_never_overwritten(setup, monkeypatch, tmp_path):
    folder = tmp_path / ".tools/vscode"
    folder.mkdir(parents=True)
    marker = folder / "user.txt"
    marker.write_text("Keep this", encoding="utf-8")
    monkeypatch.setattr(setup, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(setup, "find_editor", lambda: None)
    args = options()
    args.yes = True
    with pytest.raises(setup.SetupError, match="no se sobrescribe"):
        setup.install_editor(args)
    assert marker.read_text() == "Keep this"


@pytest.mark.parametrize("name", ["../escape", "/escape", "C:/escape", r"folder\..\escape"])
def test_zip_extraction_rejects_unsafe_paths(setup, tmp_path, name):
    archive = tmp_path / "unsafe.zip"
    with ZipFile(archive, "w") as output:
        output.writestr(name, b"unsafe")
    with pytest.raises(setup.SetupError, match="no seguro"):
        setup.extract_zip(archive, tmp_path / "extracted")
    assert not (tmp_path / "extracted").exists()


def test_zip_extraction_rejects_symlinks(setup, tmp_path):
    archive = tmp_path / "unsafe.zip"
    with ZipFile(archive, "w") as output:
        member = ZipInfo("link")
        member.create_system = 3
        member.external_attr = (stat.S_IFLNK | 0o777) << 16
        output.writestr(member, "../outside")
    with pytest.raises(setup.SetupError, match="no seguro"):
        setup.extract_zip(archive, tmp_path / "extracted")


def test_windows_editor_uses_node_cli_without_shell(setup, tmp_path):
    folder = tmp_path / "VS Code with spaces"
    editor = folder / "bin/code.cmd"
    executable = folder / "Code.exe"
    entry = folder / "resources/app/out/cli.js"
    entry.parent.mkdir(parents=True)
    executable.touch()
    entry.touch()
    command, environment = setup.code_command(editor, ["--install-extension", "ms-python.python"])
    assert command == [str(executable), str(entry), "--install-extension", "ms-python.python"]
    assert environment["ELECTRON_RUN_AS_NODE"] == "1"


def test_extensions_are_installed_from_recommendations(setup, monkeypatch, tmp_path):
    folder = tmp_path / ".vscode"
    folder.mkdir()
    (folder / "extensions.json").write_text(
        json.dumps({"recommendations": ["ms-python.python", "charliermarsh.ruff"]}),
        encoding="utf-8",
    )
    monkeypatch.setattr(setup, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(setup, "install_editor", lambda _: Path("/code"))
    calls = []
    monkeypatch.setattr(setup, "run", lambda command, **kwargs: calls.append((command, kwargs)))
    assert setup.prepare_editor(options()) == Path("/code")
    assert [command[1:] for command, _ in calls] == [
        ["--install-extension", "ms-python.python"],
        ["--install-extension", "charliermarsh.ruff"],
    ]


def test_unavailable_extension_warns_without_breaking_app_environment(
    setup, monkeypatch, tmp_path, capsys
):
    folder = tmp_path / ".vscode"
    folder.mkdir()
    (folder / "extensions.json").write_text(
        json.dumps({"recommendations": ["ms-python.vscode-pylance"]}), encoding="utf-8"
    )
    monkeypatch.setattr(setup, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(setup, "install_editor", lambda _: Path("/code"))

    def unavailable(*_args, **_kwargs):
        raise setup.SetupError("Extension unavailable")

    monkeypatch.setattr(setup, "run", unavailable)
    assert setup.prepare_editor(options()) == Path("/code")
    assert "AVISO: no se pudo instalar ms-python.vscode-pylance" in capsys.readouterr().out


@pytest.mark.parametrize("core", [True, False])
def test_setup_reuses_bootstrap_and_selected_uv(setup, monkeypatch, core):
    monkeypatch.setattr(setup.bootstrap, "configuration", lambda _: (">=0.12.10,<0.13", "3.13.15"))
    monkeypatch.setattr(setup.bootstrap, "check_uv", lambda _, executable: executable)
    calls = []
    monkeypatch.setattr(
        setup.bootstrap, "main", lambda args, **kwargs: calls.append((args, kwargs)) or 0
    )
    monkeypatch.setattr(setup, "prepare_graphics", lambda *_: None)
    monkeypatch.setattr(setup, "prepare_git", lambda *_: None)
    monkeypatch.setattr(setup, "prepare_editor", lambda _: None)
    args = ["--uv", "local tools/uv", "--skip-editor", "--non-interactive"]
    args.extend(["--core"] if core else ["--platform", "offscreen"])
    assert setup.main(args) == 0
    assert calls[0][0][0] == ("--core" if core else "--gui")
    assert calls[0][1] == {"executable": "local tools/uv"}
    if not core:
        assert calls[0][0][-2:] == ["--platform", "offscreen"]


def test_failed_bootstrap_is_not_reported_as_ready(setup, monkeypatch, capsys):
    monkeypatch.setattr(setup.bootstrap, "configuration", lambda _: (">=0.12.10,<0.13", "3.13.15"))
    monkeypatch.setattr(setup.bootstrap, "check_uv", lambda _, executable: executable)
    monkeypatch.setattr(setup.bootstrap, "main", lambda *_args, **_kwargs: 42)
    monkeypatch.setattr(setup, "prepare_git", lambda *_: pytest.fail("Bootstrap failed"))
    assert setup.main(["--uv", "uv", "--core", "--skip-editor"]) == 42
    assert "Entorno listo" not in capsys.readouterr().out


@pytest.mark.parametrize(
    "arguments", [["--core", "--platform", "xcb"], ["--skip-editor", "--open-code"]]
)
def test_conflicting_options_are_rejected_before_setup(setup, arguments):
    with pytest.raises(SystemExit) as result:
        setup.parse_args(["--uv", "uv", *arguments])
    assert result.value.code == 2
