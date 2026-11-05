# Trackfolio technical guide

Setup, catalog behavior, verification and packaging for contributors and advanced
users. For a product overview and the first steps, see the [README](README.md).

## Contents

- [Standalone executables](#standalone-executables-no-python-installation)
- [Platform requirements](#intended-compatibility)
- [Source setup](#set-up-a-pc)
- [Verification](#check-the-environment)
- [VS Code](#open-in-vs-code)
- [Starting the application](#start-the-gui)
- [Importing music](#import-music)
- [Search and filters](#search-and-filter-songs)
- [Song and batch editing](#edit-a-song)
- [Album and artist views](#browse-and-edit-albums)
- [Writing tags, artwork and NFO](#write-tags-to-music)
- [Architecture and maintenance](#architecture-and-maintenance)

## Standalone executables (no Python installation)

Build a native onefile executable with all Python dependencies and Qt resources:

```sh
uv run --locked --extra gui --group build python scripts/build.py
```

The build verifies the executable outside the checkout before producing an
archive and SHA256 checksum in `dist/`. GitHub Actions builds Linux x64, Windows
x64 and macOS Intel/Apple Silicon artifacts. End users extract the appropriate
archive and run `Trackfolio` or `Trackfolio.exe`; Python and uv are not needed.

See [standalone builds](docs/standalone-build.md) for downloads, verification,
native build requirements and system-library compatibility limits.

Arch Linux packaging and the optional AUR publishing workflow are described in
[AUR publishing](docs/aur-publishing.md), including the required manual SSH setup.

## Intended compatibility

The GUI uses Fusion, a palette, packaged fonts and icons, and custom window controls. Scaling and rasterization may vary by screen. If a Wayland compositor rejects moving or resizing the window, its native frame is enabled to preserve those operations.

| GUI platform | Initial baseline |
| --- | --- |
| Windows | Windows 10 1809+ or Windows 11, x86-64 |
| macOS | macOS 13+, Intel x86-64 or Apple Silicon ARM64 |
| GNU/Linux | x86-64, glibc 2.34+, X11 or Wayland desktop and required graphical libraries |

These are source GUI baselines. The Linux onefile build from Ubuntu 24.04 requires glibc 2.39 or newer; a local build may require newer libraries. See [standalone build limits](docs/standalone-build.md#platform-boundaries).

A compatible wheel does not prove that the GUI works on every desktop. Completed and pending checks are recorded in [VALIDATION.md](VALIDATION.md). Alpine/musl, Windows ARM64 and Linux ARM64 are outside this initial matrix.

See the [portable environment](docs/environment.md), [architecture](docs/architecture.md), [contribution guide](CONTRIBUTING.md) and [original plan](PLAN.md).

## Set up a PC

Download the repository, enter its root directory and run a single command. **You do not need to install uv or Python beforehand.** Initial setup requires Internet access and a compatible system. Clone the repository if you already have Git, or download its source ZIP from GitHub:

```sh
git clone https://github.com/Evilchuck666/Trackfolio.git
cd Trackfolio
```

**Linux and macOS:**

```sh
bash setup.sh
```

**Windows, from PowerShell:**

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\setup.ps1
```

Setup reuses a compatible uv (`>=0.13.4,<0.14`, such as 0.13.4). If none is available, it downloads the minimum version into `.tools/uv`, **without replacing system uv or modifying shell profiles**. It obtains uv-managed CPython 3.13.15, creates `.venv`, installs the GUI and development tools from `uv.lock`, and checks the environment.

If graphical libraries or Git are missing, setup proposes installing them and requests permission. If VS Code is missing, it offers to download it into `.tools/vscode`; recommended extensions are installed when the editor is available. Setup does not touch music or catalogs and can be repeated. A failed mandatory requirement returns a nonzero exit code. See [options and platform limits](docs/environment.md#single-command-setup).

To set up only Python and Qt, without downloading the editor or installing extensions:

```sh
bash setup.sh --skip-editor
```

For core-only development, add `--core`. On Windows, use the same arguments after `-File .\setup.ps1`. You do not need to activate `.venv`.

## Check the environment

From the project root:

```sh
bash setup.sh --run-uv run --locked --extra gui python scripts/doctor.py --gui
bash setup.sh --run-uv run --locked --extra gui ruff check .
bash setup.sh --run-uv run --locked --extra gui ruff format --check .
bash setup.sh --run-uv run --locked --extra gui mypy
bash setup.sh --run-uv run --locked --extra gui pytest
```

`--run-uv` runs a command with compatible uv without repeating setup. On Windows, replace `bash setup.sh` with `powershell -NoProfile -ExecutionPolicy Bypass -File .\setup.ps1`. If uv is already in `PATH`, direct `uv run ...` commands still work.

The GUI check opens the product window with a temporary database and verifies its fields and artwork. On Linux, choose X11 with `--platform xcb` or Wayland with `--platform wayland`. On a machine without a desktop, use `--platform offscreen`; that check does not validate an actual desktop. The VS Code task **Trackfolio: run headless GUI tests** runs the suite with that backend.

To check only the core:

```sh
bash setup.sh --core --skip-editor
```

`uv.lock` pins dependency versions, and `--locked` requires it to match `pyproject.toml`. Each PC must recreate its own `.venv` and `.tools`; do not copy these folders between machines. Share source through Git; keep databases, music and local configuration outside the repository.

## Open in VS Code

```sh
bash setup.sh --open-code
```

This also works when the editor was downloaded into `.tools/vscode`. If `code` is in `PATH`, you can run `code Trackfolio.code-workspace` directly. If the editor uses a different interpreter, run **Python: Select Interpreter** and choose the one in `.venv`. Workspace tasks use the launchers to find uv; integrated terminals include the local copy in their `PATH`.

## Start the GUI

From the root, after setting up the environment:

```sh
bash setup.sh --run-uv run --locked --extra gui trackfolio
```

To open a specific database, add `--database "path/to/catalog.tfo"`. The sample database is local and excluded from Git: setup prepares the application. In a new clone, use **Import music…** to create your catalog or **Open catalog…** to browse an existing one.

Without `--database`, the last opened catalog is restored if it is still available. To start without restoring it, use `--no-restore`. Open another database with **Open catalog…** and reload its records with **Refresh**. Select a song to view its details; text can be copied and lyrics are displayed as plain text.

New catalogs default to `database.tfo` in the user's data folder: on Linux, usually `~/.local/share/Trackfolio/database.tfo` (respecting `XDG_DATA_HOME`); macOS and Windows use the equivalent location through `platformdirs`. The last opened catalog does not change this destination. For development, add `--dev-root "/path/to/project"`: the destination becomes `<project>/data/database.tfo`. VS Code GUI launchers and tasks include this argument; the empty launch also uses `--no-restore`. **Choose folder…** starts in the user's home folder.

Browsing opens SQLite read-only; importing and saving edits use separate writers. Browsing and editing do not require access to the original FLAC/MP3: artwork is also stored in the catalog. Fonts, icons and styles are packaged and loaded without downloads during use.

In VS Code, run **Trackfolio: start GUI with sample** or the debug configuration **Trackfolio: GUI with sample catalog**. See the [plan and its status](docs/gui-plan.md) and [verified results](VALIDATION.md).

## Import music

1. Click **Import music…** (`Ctrl+I`).
2. Choose a folder: subfolders and `.flac`/`.mp3` files are included.
3. Create a new `.tfo` catalog or use the open catalog to add and update songs.
4. Click **Import**. The window shows progress, counts and issues, then opens the result.

You can cancel or close the application during import. Already saved files are retained, and closing waits for the current operation to finish. Reimporting the same root and path updates metadata without duplicate records; a different root or renamed file is a new location. Missing files are not deleted from the catalog. Symbolic links and junctions are not traversed.

See the [import plan and criteria](docs/import-plan.md). To inspect an individual file using the existing script, import it from the project root without modifying it:

```sh
bash setup.sh --run-uv run --locked --extra gui python scripts/import_audio.py "path/to/song.flac" --database data/database.tfo
```

Artists are shared by exact name throughout the catalog. To consolidate duplicate rows in an older catalog without importing music:

```sh
bash setup.sh --run-uv run --locked python -m trackfolio.infrastructure.database --upgrade data/database.tfo
```

A backup is created next to the file and `002_unique_artists` is applied, preserving song and album relationships. Importing or saving an edit in an older catalog also performs this upgrade; browsing or preparing a draft leaves its data intact.

Open `data/database.tfo` in SQLiteBrowser and query `track_details`. The [database guide](docs/database.md) explains tables, missing fields, backups and artwork inspection. Current SQL for a new database is in [migrations/002_current.sql](migrations/002_current.sql); the [historical initial SQL](migrations/001_initial.sql) is retained. The local database and music are excluded from Git.

## Search and filter songs

In **Songs**, search by song title, artist or album. Search is case-insensitive;
multiple words must all appear somewhere in those fields. Combine the search
with **All genres** and **All years**, or use **No genre** / **No year** to find
missing metadata. The badge shows matching songs out of the catalog total.
**Clear filters** restores the full list.

Selection is retained among matching songs; hidden songs are not included in
selection-based editing or writing. Changing filters protects unsaved drafts with
**Save / Discard / Cancel**. Filters survive refreshes and reset when opening a
different catalog. Saved changes immediately update matching results.

**Write tags…** uses the selected songs. **Write tags for the entire catalog…**
always includes the full catalog, even when filters hide some or all songs.

## Edit a song

1. Select a song and click **Edit** (`Ctrl+E`, or `Cmd+E` on macOS).
2. Change its fields. For artists and genres, add, remove or reorder full names; suggestions let you choose existing values.
3. Click **Save** (`Ctrl+S` / `Cmd+S`) to confirm, or **Cancel** (`Escape`) to restore catalog values.

Changing **Abbath → Accept** on one song reuses the artist Accept without changing other songs. Changing its album or year does not modify the album's other tracks either. Invalid values are shown next to their fields; a conflict with another write preserves the draft for review. Navigating or closing with pending edits offers save, discard or cancel.

Corrections are saved only in SQLite. **Reimporting music replaces catalog values with file tags**, including manual corrections. See the [implemented editing plan](docs/edit-plan.md).

For batch editing, select multiple songs using **Ctrl/Cmd + click**, **Shift + click** or **Ctrl/Cmd + A**, then click **Edit N songs**. You can change **Album, Artist(s), Year and Genre(s)**; individual fields are disabled. Check **Apply** for fields to replace in every selected song. Mixed values are indicated in the editor and unchecked fields are preserved; applying an empty field clears it throughout the group. Artists and genres replace the entire list with the chosen one. Saving uses a single transaction: if a song changed externally or writing fails, none are saved and the draft remains available for review.

## Browse and edit albums

The **Albums** tab supports searching by name or artist and shows artwork, shared data and tracks sorted by disc and number. **Edit album** applies checked fields to all its tracks in one transaction, preserving individual song artists. **Save album** modifies SQLite; **Write album tags…** publishes changes to the music and updates optional NFO files.

Editions are separated by library, folder and metadata. Recognized disc subdirectories are grouped when their numbers match the metadata. See the [grouping and editing rules](docs/album-view.md).

The **Artists** tab groups each artist's albums and opens editions in the album view. It includes name search and works with disconnected music. Artist photos are read from local folders and are unavailable when those folders are disconnected; album artwork is stored in the catalog. See the [artist grouping rules](docs/artist-view.md).

## Write tags to music

1. Save corrections in the catalog and select one or more songs.
2. Click **Write tags…**. The dialog immediately shows the full list.
3. Click **Write tags** to overwrite all modified tags with each song's saved values and embed local artwork. Files without text or artwork differences are skipped.

To write all saved tags for every song, click **Write tags for the entire catalog…** above the song list. This includes unselected songs and queries the complete catalog again. Review the list and click **Write tags** in the dialog to start the batch.

The dialog contains the list, progress output and **Close** and **Write tags** buttons. An empty saved value removes the corresponding tag. Multiple selection preserves each song's individual values. Audio, other picture types and tags unrelated to modified fields are preserved.

`.jpg`, `.jpeg` and `.png` files are searched for next to each song. A single image is used automatically; multiple images prompt once per folder, with a preview and an option to keep the current cover. The chosen image replaces the front cover, even without text changes. With no images, the existing cover or its absence is preserved. Cancelling the selector cancels the attempt before publication. See the [artwork rules](docs/tag-writing.md#embedding-artwork).

If `album.nfo` exists in the audio folder, its album data and the titles of target songs already present in its XML list are updated once per folder, preserving unrelated information. It is checked even if the audio is already up to date; absence does not create it or cause an error. NFO issues appear in the report and preserve batch backups. See [NFO update rules and limits](docs/tag-writing.md#optional-albumnfo-updates).

FLAC comments and ID3v2.4 are supported; ID3v2.3 is preserved when values can be represented without joining lists. Incompatible files are reported as issues. See the [matrix and limits](docs/tag-writing.md).

Each original is backed up to `.trackfolio-backups/<operation>/<id>-<name>.tfo-bak` beside its music folder. After the entire batch is successfully written and confirmed, the complete `.trackfolio-backups` directory is removed from every affected folder, including any older UUID directories it contains. Errors or cancellation retain copies for recovery. They are not imported as songs. **Close** during writing requests cancellation and waits for a safe point; files already written remain in place.

On errors, a popup offers **Save report…** with causes and backup paths. The batch and SQLite are not a single transaction. The [recovery guide](docs/tag-writing.md#recovery) explains logs, temporary files and manual backup restoration.

## Architecture and maintenance

Trackfolio uses Python 3.13, PySide6/Qt 6 and SQLite through SQLAlchemy. Domain
models and application use cases are independent of the GUI; infrastructure
adapters handle persistence, audio metadata and filesystem access. Alembic
migrations and UI resources are packaged with the application.

- [Architecture](docs/architecture.md): layers, responsibilities and boundaries.
- [Database](docs/database.md): schema, migrations and inspection.
- [Environment](docs/environment.md): bootstrap options and platform dependencies.
- [Standalone builds](docs/standalone-build.md): PyInstaller, binary verification
  and manual GitHub releases.
- [AUR publishing](docs/aur-publishing.md): recipe generation and manual SSH setup.
- [Contributing](CONTRIBUTING.md): development conventions.
- [Validation record](VALIDATION.md): completed checks and remaining platform limits.

Releases are requested manually from the workflow on `main`; pushes and pull
requests run checks and create build artifacts without publishing a release.
AUR publication is a separate opt-in step after a successful release. See the
linked publishing guides before enabling it.
