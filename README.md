# 🎵 Trackfolio

![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20GNU%2FLinux%20%7C%20macOS-blue)
![Python](https://img.shields.io/badge/python-3.13-blue)
![PySide6](https://img.shields.io/badge/PySide6-6.11.2-blue)
[![License](https://img.shields.io/badge/license-GPLv3-green)](LICENSE)
[![Build and tests](https://github.com/Evilchuck666/Trackfolio/actions/workflows/release.yml/badge.svg?branch=main)](https://github.com/Evilchuck666/Trackfolio/actions/workflows/release.yml)

**Your music, its metadata, and the stories behind each album.**

Trackfolio is a desktop application for organizing the metadata of your FLAC
and MP3 collection. Browse artists, albums and songs, correct their details,
and write the changes back to your music on Windows, GNU/Linux or macOS.

## 🧩 Why Trackfolio?

A music collection can have inconsistent artist names, missing years, different
genres for the same album, or covers that never made it into the audio files.

Trackfolio brings those details into a local catalog. You can review and edit
them even when the music drive is disconnected, then write the saved changes
to the files when you are ready.

## ✨ What it does

- Imports FLAC and MP3 folders into a local `.tfo` catalog.
- Groups your collection into **Artists**, **Albums** and **Songs** views.
- Searches songs by title, artist or album, with genre and year filters.
- Edits titles, artists, albums, years, track/disc numbers, genres and lyrics.
- Applies shared changes to an album or a selection of songs.
- Embeds local JPG/PNG covers, with a preview and a choice when several exist.
- Updates existing `album.nfo` files when writing tags.
- Shows write progress and reports, with backups retained if an operation fails
  or is cancelled.

## 🚀 Getting started

1. Open **Trackfolio** (`Trackfolio.exe` on Windows), or start it from source
   using the commands below.
2. Click **Import music…**, choose your music folder and create a catalog.
   Use **Open catalog…** if you already have a `.tfo` file.
3. Browse **Artists**, **Albums** or **Songs** and select what you want to edit.
4. Save your corrections in the catalog.
5. When ready, choose **Write tags…** or **Write album tags…**, review the list
   and confirm the write.

**Saving an edit updates the catalog. Writing tags updates the music files.**
The original files must be accessible for tag writing.

## 📥 Download and installation

Check [Releases](https://github.com/Evilchuck666/Trackfolio/releases) for published
packages. If no release is listed, use the source setup below. Successful runs
of [GitHub Actions](https://github.com/Evilchuck666/Trackfolio/actions/workflows/release.yml)
also provide downloadable build artifacts; these are development builds.

| Platform | Package filename |
| --- | --- |
| GNU/Linux x64 | `Trackfolio-linux-x64.tar.gz` |
| Windows x64 | `Trackfolio-windows-x64.zip` |
| macOS Intel | `Trackfolio-macos-x64.zip` |
| macOS Apple Silicon | `Trackfolio-macos-arm64.zip` |

Extract the package and open **Trackfolio**. Standalone builds include Python
and Qt, so you do not need to install them. Linux supports X11 and Wayland and
still needs compatible system libraries. Packages are unsigned; macOS builds
are native executables rather than `.app` bundles.

See [platform requirements](TECHNICAL_GUIDE.md#intended-compatibility) and
[standalone builds](docs/standalone-build.md) for compatibility and verification.
Arch Linux packaging is covered in the [AUR guide](docs/aur-publishing.md).

### Run from source

Clone or download the repository and enter its root folder:

```sh
git clone https://github.com/Evilchuck666/Trackfolio.git
cd Trackfolio
```

**Linux and macOS:**

```sh
bash setup.sh --skip-editor
bash setup.sh --run-uv run --locked --extra gui trackfolio
```

**Windows, from PowerShell:**

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\setup.ps1 --skip-editor
powershell -NoProfile -ExecutionPolicy Bypass -File .\setup.ps1 --run-uv run --locked --extra gui trackfolio
```

Setup downloads compatible uv and Python if needed and creates the project's
`.venv` from the lockfile. Internet access is required for initial setup; you do
not need to install Python beforehand or activate the environment yourself.

## 💾 Your catalog and music

The catalog stores metadata and album artwork locally. Browsing it does not
require the original audio files; artist photos are loaded from their folders
when available. Trackfolio remembers the last catalog you opened.

Writing tags uses each song's saved values. Local cover images can replace
embedded front covers; without an image, the existing cover is preserved.
Existing `album.nfo` files are updated, but missing ones are not created.

**Reimporting music replaces catalog metadata with the file tags**, so write
corrections to your files before reimporting if you want to keep them. Successful
write batches remove backups from the affected `.trackfolio-backups` folders;
errors and cancellation retain them. See the [tag-writing and recovery guide](docs/tag-writing.md)
for the full behavior.

## 📚 Learn more

- [Technical guide](TECHNICAL_GUIDE.md): setup, catalog behavior, development,
  verification and packaging.
- [Album view](docs/album-view.md) and [artist view](docs/artist-view.md): grouping
  rules and editing behavior.
- [Contributing](CONTRIBUTING.md): project conventions and development workflow.
- [Validation record](VALIDATION.md): tested configurations and known limits.

Built with **Python**, **Qt 6 / PySide6** and **SQLite**.

## 📄 License

Trackfolio is distributed under **GPLv3**. See [LICENSE](LICENSE).
