"""Prepare development tools and native requirements after the uv launcher starts Python."""

from __future__ import annotations

import argparse
import ctypes
import ctypes.util
import json
import os
import platform
import shlex
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path, PurePosixPath, PureWindowsPath
from urllib.request import urlopen
from zipfile import BadZipFile, ZipFile

from scripts import bootstrap, doctor

PROJECT_ROOT = Path(__file__).resolve().parents[1]

# (library, Debian/Ubuntu package, Arch/Artix package, Fedora package).
COMMON_LIBRARIES = (
    ("GL", "libgl1", "libglvnd", "libglvnd-glx"),
    ("EGL", "libegl1", "libglvnd", "libglvnd-egl"),
    ("fontconfig", "libfontconfig1", "fontconfig", "fontconfig"),
    ("xkbcommon", "libxkbcommon0", "libxkbcommon", "libxkbcommon"),
)
XCB_LIBRARIES = (
    ("X11-xcb", "libx11-xcb1", "libx11", "libX11-xcb"),
    ("xkbcommon-x11", "libxkbcommon-x11-0", "libxkbcommon-x11", "libxkbcommon-x11"),
    ("xcb-cursor", "libxcb-cursor0", "xcb-util-cursor", "xcb-util-cursor"),
    ("xcb-icccm", "libxcb-icccm4", "xcb-util-wm", "xcb-util-wm"),
    ("xcb-image", "libxcb-image0", "xcb-util-image", "xcb-util-image"),
    ("xcb-keysyms", "libxcb-keysyms1", "xcb-util-keysyms", "xcb-util-keysyms"),
    ("xcb-render-util", "libxcb-render-util0", "xcb-util-renderutil", "xcb-util-renderutil"),
    ("xcb-glx", "libxcb-glx0", "libxcb", "libxcb"),
    ("xcb-randr", "libxcb-randr0", "libxcb", "libxcb"),
    ("xcb-shape", "libxcb-shape0", "libxcb", "libxcb"),
    ("xcb-sync", "libxcb-sync1", "libxcb", "libxcb"),
    ("xcb-xfixes", "libxcb-xfixes0", "libxcb", "libxcb"),
    ("xcb-xkb", "libxcb-xkb1", "libxcb", "libxcb"),
    ("xcb-util", "libxcb-util1", "xcb-util", "xcb-util"),
)
WAYLAND_LIBRARIES = (
    ("wayland-client", "libwayland-client0", "wayland", "wayland-libs"),
    ("wayland-cursor", "libwayland-cursor0", "wayland", "wayland-libs"),
    ("wayland-egl", "libwayland-egl1", "wayland", "wayland-libs"),
)


class SetupError(Exception):
    """A setup step failed or needs an explicit decision from the user."""


def command_text(command: list[str]) -> str:
    return subprocess.list2cmdline(command) if os.name == "nt" else shlex.join(command)


def run(command: list[str], *, env: dict[str, str] | None = None) -> None:
    print(f"Ejecutando: {command_text(command)}", flush=True)
    try:
        result = subprocess.run(command, cwd=PROJECT_ROOT, env=env, check=False)
    except OSError as exc:
        raise SetupError(f"Could not run {command[0]}: {exc}") from exc
    if result.returncode:
        raise SetupError(f"Command failed ({result.returncode}): {command_text(command)}")


def confirm(message: str, args: argparse.Namespace) -> bool:
    if args.yes:
        print(f"Autorizado mediante --yes: {message}")
        return True
    if args.non_interactive or not sys.stdin.isatty():
        return False
    try:
        return input(f"{message} [y/N] ").strip().lower() in ("s", "si", "sí", "y", "yes")
    except EOFError:
        return False


def linux_family() -> str | None:
    try:
        release = platform.freedesktop_os_release()
    except OSError:
        return None
    names = {release.get("ID", ""), *release.get("ID_LIKE", "").split()}
    for family, members in (
        ("debian", {"debian", "ubuntu"}),
        ("arch", {"arch", "artix"}),
        ("fedora", {"fedora", "rhel", "centos"}),
    ):
        if names & members:
            return family
    return None


def package_commands(packages: list[str]) -> list[list[str]]:
    if sys.platform != "linux":
        raise SetupError("System package installation is only supported on Linux.")
    family = linux_family()
    manager = {"debian": "apt-get", "arch": "pacman", "fedora": "dnf"}.get(family or "")
    if manager is None or shutil.which(manager) is None:
        raise SetupError(
            "No supported package manager found: apt-get, pacman or dnf. Install packages manually."
        )
    prefix: list[str] = []
    if os.geteuid() != 0:
        sudo = shutil.which("sudo")
        if sudo is None:
            raise SetupError(
                "You need sudo, or must install packages manually as an administrator."
            )
        prefix = [sudo]
    if manager == "apt-get":
        return [
            [*prefix, manager, "update"],
            [*prefix, manager, "install", "--no-install-recommends", "-y", *packages],
        ]
    if manager == "pacman":
        return [[*prefix, manager, "-S", "--needed", "--noconfirm", *packages]]
    return [[*prefix, manager, "install", "-y", *packages]]


def graphical_platform(requested: str | None) -> str | None:
    if requested is not None or platform.system() != "Linux":
        return requested
    if os.environ.get("WAYLAND_DISPLAY") and os.environ.get("XDG_SESSION_TYPE") != "x11":
        return "wayland"
    if os.environ.get("DISPLAY"):
        return "xcb"
    print("No graphical session: using offscreen; this does not validate an actual desktop.")
    return "offscreen"


def library_available(name: str) -> bool:
    filename = ctypes.util.find_library(name)
    if filename is None:
        return False
    try:
        ctypes.CDLL(filename)
    except OSError:
        return False
    return True


def prepare_graphics(qt_platform: str | None, args: argparse.Namespace) -> None:
    result = doctor.check_gui_platform()
    if not result.ok:
        raise SetupError(result.detail)
    if platform.system() != "Linux":
        return
    libraries: tuple[tuple[str, str, str, str], ...] = COMMON_LIBRARIES
    if qt_platform == "xcb":
        libraries += XCB_LIBRARIES
    elif qt_platform == "wayland":
        libraries += WAYLAND_LIBRARIES
    missing = [item for item in libraries if not library_available(item[0])]
    if not missing:
        return
    names = ", ".join(item[0] for item in missing)
    print(f"Missing graphical libraries: {names}")
    index = {"debian": 1, "arch": 2, "fedora": 3}.get(linux_family() or "")
    if index is None:
        raise SetupError(f"Install these libraries manually and run setup again: {names}.")
    packages = sorted({item[index] for item in missing})
    commands = package_commands(packages)
    for command in commands:
        print(f"Proposed installation: {command_text(command)}")
    if not confirm("Install the system graphical libraries?", args):
        raise SetupError(
            "The required libraries were not authorized. The system has not been modified."
        )
    for command in commands:
        run(command)
    remaining = [item[0] for item in missing if not library_available(item[0])]
    if remaining:
        raise SetupError(
            f"Siguen faltando bibliotecas: {', '.join(remaining)}. Consulta docs/environment.md."
        )


def prepare_git(args: argparse.Namespace) -> None:
    executable = shutil.which("git")
    if executable:
        print(f"Git disponible: {executable}")
        return
    system = platform.system()
    if system == "Linux":
        try:
            commands = package_commands(["git"])
        except SetupError as exc:
            print(f"WARNING: Git is not installed. {exc}")
            return
    elif system == "Darwin" and shutil.which("brew"):
        commands = [["brew", "install", "git"]]
    elif system == "Windows" and shutil.which("winget"):
        commands = [
            [
                "winget",
                "install",
                "--id",
                "Git.Git",
                "--exact",
                "--source",
                "winget",
                "--accept-source-agreements",
                "--accept-package-agreements",
            ]
        ]
    else:
        print(
            "AVISO: instala Git desde https://git-scm.com/install/ "
            "for version control; the app does not need it."
        )
        return
    for command in commands:
        print(f"Proposed installation: {command_text(command)}")
    if confirm("Install Git for development?", args):
        for command in commands:
            run(command)
        print("Git installed. On Windows you may need to open a new terminal to find it in PATH.")
    else:
        print("WARNING: Git not installed; you can use the app or install it later.")


def editor_cli(root: Path) -> Path:
    if platform.system() == "Darwin":
        return root / "Visual Studio Code.app/Contents/Resources/app/bin/code"
    return root / ("bin/code.cmd" if platform.system() == "Windows" else "bin/code")


def find_editor() -> Path | None:
    installed = shutil.which("code")
    if installed:
        return Path(installed).resolve()
    candidates = [editor_cli(PROJECT_ROOT / ".tools/vscode")]
    if platform.system() == "Darwin":
        candidates.extend(
            editor_cli(base) for base in [Path("/Applications"), Path.home() / "Applications"]
        )
    elif platform.system() == "Windows":
        for variable in ["LOCALAPPDATA", "ProgramFiles"]:
            base = os.environ.get(variable)
            if base:
                candidates.append(
                    Path(base)
                    / (
                        "Programs/Microsoft VS Code/bin/code.cmd"
                        if variable == "LOCALAPPDATA"
                        else "Microsoft VS Code/bin/code.cmd"
                    )
                )
    return next((candidate for candidate in candidates if candidate.is_file()), None)


def editor_download() -> tuple[str, str]:
    system, machine = platform.system(), platform.machine().lower()
    target = {
        ("Linux", "x86_64"): "linux-x64",
        ("Windows", "amd64"): "win32-x64-archive",
        ("Windows", "x86_64"): "win32-x64-archive",
        ("Darwin", "x86_64"): "darwin",
        ("Darwin", "arm64"): "darwin-arm64",
    }.get((system, machine))
    if target is None:
        raise SetupError(f"No VS Code download configured for {system} {machine}.")
    return f"https://update.code.visualstudio.com/latest/{target}/stable", (
        ".tar.gz" if system == "Linux" else ".zip"
    )


def download(url: str, target: Path) -> None:
    print(f"Descargando: {url}", flush=True)
    with urlopen(url, timeout=120) as response, target.open("wb") as output:
        if not response.geturl().startswith("https://"):
            raise SetupError("The download was redirected outside HTTPS.")
        shutil.copyfileobj(response, output)


def extract_zip(archive: Path, destination: Path) -> None:
    with ZipFile(archive) as source:
        for member in source.infolist():
            name = PurePosixPath(member.filename)
            if (
                name.is_absolute()
                or ".." in name.parts
                or PureWindowsPath(member.filename).drive
                or "\\" in member.filename
                or stat.S_ISLNK(member.external_attr >> 16)
            ):
                raise SetupError("The editor archive contains an unsafe path or link.")
        source.extractall(destination)


def install_editor(args: argparse.Namespace) -> Path | None:
    installed = find_editor()
    if installed is not None:
        return installed
    if not confirm("Download official VS Code into .tools/vscode for this project?", args):
        print("WARNING: VS Code not set up; the application and Python tools are still available.")
        return None
    tools = PROJECT_ROOT / ".tools"
    destination = tools / "vscode"
    if destination.exists():
        raise SetupError(
            f"{destination} exists but contains no recognizable editor. "
            "Check it; it will not be overwritten."
        )
    tools.mkdir(exist_ok=True)
    url, suffix = editor_download()
    with tempfile.TemporaryDirectory(prefix=".vscode-download-", dir=tools) as temporary:
        root = Path(temporary)
        archive = root / f"vscode{suffix}"
        download(url, archive)
        unpacked = root / "unpacked"
        unpacked.mkdir()
        system = platform.system()
        if system == "Linux":
            with tarfile.open(archive) as source:
                source.extractall(unpacked, filter="data")
            extracted = unpacked / "VSCode-linux-x64"
        elif system == "Darwin":
            run(["ditto", "-x", "-k", str(archive), str(unpacked)])
            extracted = unpacked
        else:
            extract_zip(archive, unpacked)
            extracted = unpacked
        if not editor_cli(extracted).is_file():
            raise SetupError("The download does not contain the expected VS Code executable.")
        extracted.rename(destination)
    return editor_cli(destination)


def code_command(editor: Path, arguments: list[str]) -> tuple[list[str], dict[str, str] | None]:
    if editor.suffix.lower() == ".cmd":
        # Use Electron's Node CLI instead of invoking a batch file through a shell.
        executable = editor.parent.parent / "Code.exe"
        entry_point = editor.parent.parent / "resources/app/out/cli.js"
        if not executable.is_file() or not entry_point.is_file():
            raise SetupError("Cannot find the VS Code executable or CLI next to code.cmd.")
        environment = dict(os.environ, ELECTRON_RUN_AS_NODE="1")
        return [str(executable), str(entry_point), *arguments], environment
    return [str(editor), *arguments], None


def prepare_editor(args: argparse.Namespace) -> Path | None:
    if args.skip_editor:
        return None
    editor = install_editor(args)
    if editor is None:
        return None
    try:
        recommendations = json.loads(
            (PROJECT_ROOT / ".vscode/extensions.json").read_text(encoding="utf-8")
        )["recommendations"]
    except (OSError, ValueError, KeyError) as exc:
        raise SetupError(f"Cannot read recommended extensions: {exc}") from exc
    if not isinstance(recommendations, list) or not all(
        isinstance(item, str) for item in recommendations
    ):
        raise SetupError("The recommended extensions list is invalid.")
    for extension in recommendations:
        command, environment = code_command(editor, ["--install-extension", extension])
        try:
            run(command, env=environment)
        except SetupError as exc:
            print(f"WARNING: Could not install {extension}: {exc}")
            print("Try again, or use official VS Code if your editor uses a different marketplace.")
    return editor


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--core", action="store_true", help="Set up without Qt.")
    mode.add_argument("--gui", action="store_true", help="Set up with Qt (default).")
    parser.add_argument("--uv", required=True, help=argparse.SUPPRESS)
    parser.add_argument("--platform", choices=("offscreen", "xcb", "wayland"))
    parser.add_argument("--qt-timeout", type=bootstrap.positive_timeout, default=15.0)
    parser.add_argument(
        "--skip-editor",
        action="store_true",
        help="Do not download the editor or install extensions.",
    )
    parser.add_argument(
        "--non-interactive",
        action="store_true",
        help="Do not prompt; reject proposals requiring permission unless --yes is supplied.",
    )
    parser.add_argument(
        "--yes", action="store_true", help="Explicitly authorize proposed installations."
    )
    parser.add_argument(
        "--open-code",
        action="store_true",
        help="Open the workspace after setting up the environment.",
    )
    args = parser.parse_args(argv)
    if args.core and args.platform:
        parser.error("--platform requires the GUI.")
    if args.skip_editor and args.open_code:
        parser.error("--skip-editor cannot be combined with --open-code.")
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        requirement, _ = bootstrap.configuration(PROJECT_ROOT)
        executable = bootstrap.check_uv(requirement, executable=args.uv)
        qt_platform = None if args.core else graphical_platform(args.platform)
        if not args.core:
            prepare_graphics(qt_platform, args)
        bootstrap_args = ["--core" if args.core else "--gui", "--qt-timeout", str(args.qt_timeout)]
        if qt_platform:
            bootstrap_args.extend(["--platform", qt_platform])
        result = bootstrap.main(bootstrap_args, executable=executable)
        if result:
            return result
        prepare_git(args)
        editor = prepare_editor(args)
        launcher = (
            "powershell -ExecutionPolicy Bypass -File setup.ps1"
            if platform.system() == "Windows"
            else "bash setup.sh"
        )
        print("\nEnvironment ready. No need to activate .venv or modify the system PATH.")
        if editor:
            print(f"VS Code disponible: {launcher} --open-code")
        else:
            print("Si tienes VS Code: code Trackfolio.code-workspace")
        if not args.core:
            print(
                f"Launch the application: {launcher} --run-uv run --locked --extra gui trackfolio"
            )
            print(
                "To view songs, open an existing catalog or import music; "
                "setup does not touch that data."
            )
        if args.open_code:
            if editor is None:
                raise SetupError("No editor available for --open-code.")
            command, environment = code_command(
                editor, [str(PROJECT_ROOT / "Trackfolio.code-workspace")]
            )
            run(command, env=environment)
    except (
        SetupError,
        bootstrap.BootstrapError,
        OSError,
        ValueError,
        tarfile.TarError,
        BadZipFile,
    ) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
