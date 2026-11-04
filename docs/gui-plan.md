# Plan for Trackfolio's first GUI

Status: GUI implemented and locally validated on October 7, 2026. The database and sample are ready. The window opens a SQLite catalog and displays songs through Qt 6, with the GUI as the priority interface.

## Expected result

A window opens a catalog, lists songs and selects a record to display metadata/artwork from SQLite. The viewer works even when original music is unavailable on that machine: artwork is stored in the database.

This increment provides catalog opening, list refresh, selection and all requested fields. Fields are read-only and support copying. Song editing has its [own plan](edit-plan.md), implemented and locally validated on October 9, 2026. Graphical import and catalog generation have an [implementation plan](import-plan.md), executed and locally checked on October 9, 2026; TUI and API remain future possibilities.

## 1. Contracts and startup

- [x] Keep `GetTrack` for selected-file details.
- [x] Add immutable `CatalogSummary`, repository `list_summaries()` and `ListTrackSummaries`, preserving `ListTracks`.
- [x] Summaries return identifiers, title, artists, album, year and path. Query specific columns without loading every song's BLOBs, lyrics or original tags. No migration is required.
- [x] Construct engine, repository and use cases at a composition point. Widgets, table model and presenter receive use cases; they do not import SQLAlchemy, Alembic or Mutagen or execute SQL.
- [x] Encapsulate existing-catalog opening/validation and resource closure in infrastructure. Missing paths, unrelated databases and incompatible revisions produce recoverable messages. Opening never silently creates another catalog or changes its schema.
- [x] Add the GUI package entry point and `trackfolio` launcher through `project.gui-scripts`, avoiding an extra Windows console. Qt loads only at graphical startup; core installation/tests remain PySide6-free.
- [x] Support `--database` and **Open catalog…**. Without an argument, open the last valid catalog or show an empty window. Store local configuration through `platformdirs`, outside the repository.

Open the sample from the root:

```sh
uv run --locked --extra gui python -m trackfolio.interfaces.gui --database data/database.tfo
```

Pass paths as arguments, quoting spaces. The installed package must work from any working directory with a database outside the project.

## 2. Window and data layout

- [x] Resizable window with a song-list/detail splitter.
- [x] Table columns **Song**, **Artist(s)**, **Album**, **Year** and **File**. File distinguishes untitled records without inventing musical metadata.
- [x] Select the first record when opening a populated database. Refresh retains selection by `file_id` if available.
- [x] **Open catalog…**, **Refresh** and **Exit**, keyboard shortcuts, visible focus and navigation between list/fields.
- [x] Status bar with catalog, record count and loading status; empty detail without selection.

| Detail group | Fields |
| --- | --- |
| Identification | Cover thumbnail, song and artist(s) |
| Album | Name and year |
| Numbering | Track number/total and disc number/total |
| Classification | Genre(s), preserving names and order |
| Lyrics | Selectable plain text with line breaks and scrolling |

Numbering uses separate nearby fields. A track number without a total leaves the total blank. `None` and empty collections display as empty text, without zeros or assumed values. Lyrics remain plain text rather than interpreted HTML.

The thumbnail uses `GetTrack` bytes and preserves aspect ratio. Embedded artwork versus `album.jpg` is already resolved during import. Missing or undecodable images leave the area blank while other details remain available. The GUI does not reread music files.

## 3. Shared appearance and resources

- [x] Qt Widgets with explicit **Fusion**, Trackfolio palette/styles and shared spacing, borders and sizes.
- [x] Font variants, license, styles and original icons in `trackfolio.resources`. Load fonts with `QFontDatabase` and files with `importlib.resources`, independent of working directory and desktop icon theme.
- [x] Non-native Qt dialogs and menus inside the window.
- [x] Qt-drawn title bar/window controls covering frame appearance. Validate move, resize, minimize, maximize/restore, close, focus and accessibility. Use Qt-exposed system move/resize operations, especially on Wayland; check results and backend capabilities.
- [x] Logical layouts/sizes supporting display scaling. Review at 100%, 150% and 200%, including thumbnail and text readability.

Design, assets, controls and layout are shared. Rasterization and physical pixels can vary by system/display. Fusion alone does not control the system frame, hence the custom frame is part of the plan. References: [Fusion](https://doc.qt.io/qt-6.11/qstylefactory.html), [fonts](https://doc.qt.io/qt-6.11/qfontdatabase.html#addApplicationFontFromData), [DPI](https://doc.qt.io/qt-6.11/highdpi.html) and [window movement](https://doc.qt.io/qt-6.11/qwindow.html#startSystemMove).

## 4. Loading and interface states

- [x] List/detail queries in workers keep the window responsive. Each operation obtains/closes its connection; SQLite connections are not shared between threads.
- [x] Widgets/presentation images are created and changed on the GUI thread. Workers return dataclasses or application errors.
- [x] Identify requests to discard stale responses during rapid song/catalog switching.
- [x] Clear every field on selection changes, including prior artwork, lyrics and numbering.
- [x] Handle absent catalogs, empty databases, removed selections, inaccessible/locked catalogs and query failures. Missing metadata is valid and does not generate warnings.
- [x] Close/change catalogs without leaked workers/connections or results delivered to destroyed windows.

## 5. Functional checks

- [x] Listing summaries does not retrieve BLOBs, lyrics or `raw_tags`.
- [x] Test widgets/selection with PySide6 QtTest and pytest, using synthetic data and temporary databases.
- [x] Complete, partial and metadata-free records; multiple songs/genres; Unicode; multiline lyrics; valid, absent and undecodable artwork; empty databases and recoverable read errors.
- [x] Rapid selection and out-of-order responses.
- [x] GUI → use cases → SQLite when music no longer exists.
- [x] Manually validate the real sample: **Run If You Can**, **Accept**, **Breaker**, **1981**, **3/10**, **1/1**, **Heavy Metal**, **500 × 500** JPEG and empty lyrics. Compare with SQLiteBrowser `track_details`.
- [x] Maintain Ruff, formatting, mypy and core tests.

## 6. Reproducible delivery and cross-platform validation

- [x] Retain uv-managed CPython 3.13.15, uv `>=0.13.4,<0.14` and PySide6 6.11.2. Version any required dependencies in `pyproject.toml`/`uv.lock`. Initially use installed modules.
- [x] Extend `doctor.py` to verify real resources and product-window startup, keeping subprocess isolation.
- [x] Add VS Code tasks/debugging for the sample GUI with workspace paths and separate arguments.
- [x] Build wheel/source distribution containing all resources. Install wheel and locked dependencies into a clean environment; verify the GUI from another directory without checkout or sample music.
- [x] Extend GitHub Actions to the product GUI on Windows x86-64, GNU/Linux x86-64 and macOS Intel/Apple Silicon. Retain Qt-free core, `offscreen` GUI and available native/X11 checks.
- [ ] Record visual/interaction review on real desktops, including local Wayland. Separate measured/pending results: `offscreen` proves neither desktop appearance nor frame behavior. Local Wayland/X11 startup and 100/150/200% screenshots are complete; manual Windows/macOS comparison remains pending. The four-platform automatic matrix passes GitHub Actions run 37659500266.
- [x] Update README, environment and VALIDATION with launch commands, new-PC setup and observed results.

This phase delivers an installable, reproducible Python/uv project with Qt, assets and Python dependencies resolved for each platform. Standalone executables bundling the interpreter will be designed in a later delivery.

The initial matrix remains Windows 10 1809+/11 x86-64, macOS 13+ Intel/Apple Silicon and GNU/Linux x86-64 with glibc 2.34+ and a supported graphical backend. uv rebuilds the environment; `.venv` is not moved between PCs. Native graphical libraries and desktop sessions remain system requirements, with diagnostics/instructions in [environment.md](environment.md). Compatibility is verified against this matrix and its requirements.

## Order and phase completion

Implement stages 1–2 for a sample-browsing window, complete appearance/loading in stages 3–4, then tests, packaging and cross-platform checks in stages 5–6.

The phase ends when all sample fields display, absent values remain blank, the installed package works and functional checks cover the CI matrix. Real visual/interaction results are recorded separately; no platform is confirmed before verification.
