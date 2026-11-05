# Standalone executables

Trackfolio can be distributed as a PyInstaller **onefile** executable. Users do
not need Python, uv or a virtual environment. Python, the application, its Python
dependencies, Qt plugins, fonts, icons and database migrations are bundled.

## Build

Build on the target operating system and architecture. After installing uv (or
running the project's setup launcher), run from the checkout:

```sh
uv run --locked --extra gui --group build python scripts/build.py
```

The VS Code task **Trackfolio: build standalone executable** runs the same command
through the project's setup launcher. PyInstaller is pinned in the optional
`build` dependency group; it is not required to run or develop the core.

| Build host | Executable | Distribution archive |
| --- | --- | --- |
| Linux x64 | `dist/Trackfolio` | `dist/Trackfolio-linux-x64.tar.gz` |
| Windows x64 | `dist/Trackfolio.exe` | `dist/Trackfolio-windows-x64.zip` |
| macOS Intel | `dist/Trackfolio` | `dist/Trackfolio-macos-x64.zip` |
| macOS Apple Silicon | `dist/Trackfolio` | `dist/Trackfolio-macos-arm64.zip` |

Each archive contains the executable and the project license. A matching
`.sha256` file records the archive checksum. Extract the archive and run the
executable. On Unix, restore executable permission with `chmod +x Trackfolio`
if your extraction tool removes it. The macOS output is a native executable,
not an `.app` bundle. These builds are unsigned and are not notarized.

The **Cross-platform environment** workflow builds all four targets, checks
their offscreen and native Qt backends, and uploads archives and checksums as
workflow artifacts. Pushes and pull requests do not publish releases.

## Publish a release

1. Set `project.version` in `pyproject.toml` to the intended version, update
   `uv.lock` with `uv lock`, and commit and push these changes to `main`.
2. Open **Actions → Cross-platform environment → Run workflow** on GitHub.
3. Select `main` and enter the version without `v` (for example, `0.1.0`).
   Leave it empty to build and verify without publishing.

After all four targets pass, the publication job checks that the version matches
`pyproject.toml`, rejects existing tags, downloads the packages from that same
run, and verifies their checksums. It creates `v<version>` on the tested commit
and publishes a release with the four archives, `SHA256SUMS.txt` and generated
release notes. Only that job receives `contents: write`. Manual runs are not
automatically cancelled by subsequent pushes. Publication from other branches
is skipped. Existing releases are never overwritten; a failed publication that
already created a tag must be inspected before retrying.

To also publish `trackfolio-bin` on AUR, first complete the
[AUR authentication setup](aur-publishing.md), then enable `publish_aur` when
starting the workflow. It is disabled by default and runs after the release.

## Verification

Before archiving, the build script copies only the executable into a temporary
directory with spaces and Unicode in its name. It clears Python environment
variables and removes Python from `PATH`. The executable verifies resource
hashes and exercises the GUI, catalog creation/migrations, import, editing,
tag writing, artwork, NFO updates and album/artist views using temporary data.
No personal catalog or music is used. A missing or incomplete JSON report fails
the build, including for Windows executables without a console.

To repeat verification without rebuilding:

```sh
uv run --locked --extra gui --group build python scripts/build.py --verify-only dist/Trackfolio
```

Use `dist/Trackfolio.exe` on Windows. Add `--platform xcb`, `--platform windows`
or `--platform cocoa` to test the native desktop backend. Linux X11 verification
requires a display or Xvfb.

## Platform boundaries

Onefile does not mean a universal executable. Build separately for each OS and
CPU architecture. PyInstaller extracts bundled files into a temporary directory
when starting; that directory must allow execution and have enough free space.

Linux still requires compatible system libraries (including glibc and the
graphics/display stack). Build on the oldest distribution you intend to
support: the CI Linux build uses Ubuntu 24.04 (glibc 2.39), so the source GUI's
glibc 2.34 baseline is not a promise for this binary. A locally built binary may
require newer libraries. Windows and macOS compatibility also depends on the
build host, Python and Qt; successful CI only validates the runners in the
workflow. See [VALIDATION.md](../VALIDATION.md) for actual verification results.

See PyInstaller's [operating model](https://pyinstaller.org/en/stable/operating-mode.html)
and [usage documentation](https://pyinstaller.org/en/stable/usage.html).
