# Trackfolio validation

This record preserves checks from each phase. Initial infrastructure was validated on October 6, 2026; the catalog and its first GUI were implemented on October 7. Later deliveries, including tag writing, are recorded below.

## Local checks

Machine: GNU/Linux x86-64, Omarchy, glibc 2.44, Wayland session with XWayland available. The environment uses uv 0.12.10 and uv-managed CPython 3.13.15. System Python is preserved.

| Check | Result |
| --- | --- |
| Installation from `uv.lock` with `gui` extra | Passed |
| GUI setup with the README command | Passed; Wayland backend |
| Qt 6.11.2/Fusion window and event loop with Wayland | Passed |
| Qt 6.11.2/Fusion window and event loop with X11 (`xcb`) | Passed |
| Headless Qt (`offscreen`) in a clean copy | Passed; does not count as a desktop test |
| SQLite 3.53.1 through SQLAlchemy: writes, transactions and Unicode reads | Passed |
| Clean copy without `.venv`, in a path with spaces and Unicode characters | Core and GUI setup passed |
| Core in that copy, without PySide6 installed | Passed; domain and application importable |
| Repeated setup | Passed; lock unchanged |
| Modified manifest with `--locked` | Rejected with an outdated-lock error |
| Script tests | 23 passed |
| Ruff and formatting check | Passed |
| Strict mypy | Passed: 9 source files |
| Wheel and source distribution | Built successfully |
| Wheel installed without dependencies in a temporary environment outside the source tree | Package and resources importable |
| VS Code workspace and tasks | Valid JSON, relative paths, `process` tasks; Ruff extension installed |
| Workflow | Validated with actionlint 1.7.12 and SHA-pinned actions |

No system graphics libraries needed installing on this PC. Instructions for other machines are in [docs/environment.md](docs/environment.md).

Main resolved versions: SQLAlchemy 2.1.3, Alembic 1.20.0, Mutagen 1.48.1, platformdirs 4.12.3 and PySide6/Essentials/Addons/shiboken6 6.11.2. Complete versions and hashes are in `uv.lock`.

## Initial infrastructure automated matrix

The workflow checks clean core installation without Qt, locked GUI installation, diagnostics, 23 tests, Ruff, mypy, builds and wheel resources. Linux adds X11 under Xvfb; Windows and macOS check native backends as well as `offscreen`.

| Runner | Architecture | Status |
| --- | --- | --- |
| Ubuntu 24.04 | x86-64 | Passed: core, Qt offscreen/X11, tests and distribution |
| Windows Server 2022 | x86-64 | Passed: core, Qt offscreen/native, tests and distribution |
| macOS 15 Intel | x86-64 | Passed: core, Qt offscreen/native, tests and distribution |
| macOS 15 Apple Silicon | ARM64 | Passed: core, Qt offscreen/native, tests and distribution |

All four jobs passed in [GitHub Actions run 37457968238](https://github.com/Evilchuck666/Trackfolio/actions/runs/37457968238), on revision `d201961976d20f78b07d80e6e30071bf28411b77`. This subsequent record only updates documentation.

Runners do not cover every advertised minimum version or every desktop. The product GUI record follows below.

## Initial catalog: local checks on October 7, 2026

Migration `001_initial` creates eleven catalog tables, the Alembic revision table and the `track_details` view. Its [migrations/001_initial.sql](migrations/001_initial.sql) export matches the schema applied online. The catalog uses Python contracts without Qt, a Mutagen reader and a SQLAlchemy repository.

| Check | Result |
| --- | --- |
| Complete local suite | 73 passed: environment, reader, migrations and catalog |
| Ruff, formatting and strict mypy | Passed; mypy checked 21 source files |
| Initial SQL versus Alembic migration | Same tables, constraints, indexes and view |
| Wheel installed with locked dependencies and hashes, outside the checkout | Packaged migration executed successfully; foreign keys enabled and revision `001_initial` |
| Missing metadata in synthetic FLAC/MP3 and catalog | `NULL` fields, empty collections; import and queries without exceptions |
| Embedded artwork, front-cover preference and `album.jpg` fallback | Covered by synthetic tests |
| Repeated import of the supplied FLAC | One file and one track; identifiers preserved |
| Local catalog integrity | `integrity_check=ok`; no `foreign_key_check` rows |
| Original FLAC | Identical SHA-256 before and after; no writes |

The local `data/trackfolio.sqlite3` database contains “Run If You Can” by Accept, album “Breaker”, year 1981, track 3/10, disc 1/1 and genre Heavy Metal. Its eleven text tags are retained in `raw_tags`; lyrics and album artist are absent. The embedded 500 × 500, 385192-byte JPEG artwork is retained as a BLOB matching the FLAC's bytes.

The matrix above covers initial infrastructure. The database, music and actual artwork are excluded from Git. After user validation of this phase, the viewer below was implemented.

## Catalog GUI: October 7, 2026

The window queries SQLite read-only through `ListTrackSummaries` and `GetTrack`. The list does not fetch artwork, lyrics or original tags; details fetch those only for the selection. Widgets and controller do not import SQLAlchemy or Mutagen. Inter 4.1 fonts, license, original SVGs and QSS are included with a hash manifest.

| Local check | Result |
| --- | --- |
| Complete suite, GUI with `offscreen` | 122 passed |
| Core in a clean environment without PySide6 | 101 passed; 2 GUI modules skipped |
| Ruff, formatting, mypy | Passed; mypy checked 33 source files |
| Product window, events and details on Wayland | Passed |
| Product window, events and details on X11 | Passed |
| `offscreen` diagnostics | Passed; does not establish real desktop behavior |
| Sample database versus window fields | Song, artist, album, year, numbering, genre, artwork and empty lyrics match |
| Screenshots at 100%, 150% and 200% scale | Generated with expected data; layout and artwork reviewed locally |
| Asynchronous selection and refresh | Reject stale responses, preserve latest intent and clear details when rows disappear |
| Empty, unknown, missing or inaccessible catalog | Recoverable states; opening creates or migrates no database |
| Widget tests | Selection, copying, empty fields, invalid/proportional artwork and window controls |
| Wheel and sdist | Built with fonts, license, icons, QSS and migrations |
| Wheel installed outside the checkout | Core without Qt and GUI with locked dependencies/hashes; window and data checked |
| Workflow and VS Code | Valid actionlint 1.7.12 and JSON; GUI launch/debug tasks |

Catalogs and screenshots containing sample artwork remain in `data/`, excluded from Git. The GUI can query data even when original music is missing. The `trackfolio` launcher is installed through `project.gui-scripts`.

All four GUI jobs passed in [run 37659500266](https://github.com/Evilchuck666/Trackfolio/actions/runs/37659500266), on `63f822cbd3298e117a1a864ed24fe9eaadbfda05`, branch `gui`:

| Runner | Product result |
| --- | --- |
| Ubuntu 24.04 x86-64 | Core without Qt, offscreen/X11 GUI, 122 tests, types and installed wheel passed |
| Windows Server 2022 x86-64 | Core without Qt, offscreen/native GUI, 122 tests, types and installed wheel passed |
| macOS 15 Intel | Core without Qt, offscreen/native GUI, 122 tests, types and installed wheel passed |
| macOS 15 Apple Silicon | Core without Qt, offscreen/native GUI, 122 tests, types and installed wheel passed |

Manual visual review on Windows and macOS remains pending. Automated tests verify fields, fonts, resources and startup; they do not prove pixel identity across displays. On Wayland, a compositor rejecting move/resize operations triggers a native-frame fallback.

## Compatible uv range: October 8, 2026

The manifest and setup accept `>=0.12.10,<0.13`. Version comparison is numeric and checks both bounds before installation and synchronization. CPython 3.13.15, PySide6 6.11.2, `uv_build==0.12.10` and `uv.lock` contents remain unchanged.

Machine used: Artix Linux x86-64, glibc 2.44, X11 session. System uv is 0.12.23; checks with 0.12.10 use `uv tool run --from uv==0.12.10` without replacing it.

| Local check | Result |
| --- | --- |
| GUI setup with uv 0.12.10 and 0.12.23 | Passed with `offscreen`, from the same lock |
| Complete suite with uv 0.12.10 | 152 passed |
| Complete suite with uv 0.12.23 | 152 passed |
| Setup tests | 40 passed; bounds, later patches, numeric comparison, invalid ranges and installation messages |
| Ruff, formatting and strict mypy | Passed; mypy checked 33 source files |
| Product window and events on X11 with uv 0.12.23 | Passed; GUI diagnostics without errors |
| Wheel and source distribution with uv 0.12.23 | Built successfully with the pinned backend |
| Workflow | actionlint 1.7.12 passed; YAML and eight unique combinations checked |

The GitHub Actions matrix is configured for uv 0.12.10 and 0.12.23 on the four existing platforms. These eight jobs have not yet run on GitHub Actions with the range changes; earlier cross-platform results correspond to the revisions linked in their sections.

## Setup from a clone or ZIP: October 8, 2026

`setup.sh` and `setup.ps1` start setup without requiring Python or uv in `PATH`. They reuse compatible uv or download the minimum version into `.tools/uv`, without replacing system installations or editing shell profiles. `scripts/setup.py` checks graphics libraries, delegates Python setup to `bootstrap.py` and offers Git and VS Code setup. System installations require confirmation. VS Code tasks use the same launchers.

Local checks ran on the Artix Linux x86-64 machine above. PowerShell launcher tests used PowerShell 7.6.6 downloaded into `/tmp/opencode`, with SHA-256 checked against GitHub's published value; it was not installed system-wide.

| Local check | Result |
| --- | --- |
| Complete suite with uv 0.12.10 | 210 passed, including PowerShell tests |
| Complete suite with uv 0.12.23 | 210 passed, including PowerShell tests |
| Bootstrap, setup and launcher tests | 98 passed; uv selection, consent, arguments, Unicode paths, safe extraction and errors |
| Core in a clean copy without PySide6 | 189 passed; 2 GUI modules skipped |
| Bash launcher with system uv | GUI setup passed with `offscreen` and X11 (`xcb`) |
| PowerShell 7.6.6 launcher with system uv, on Linux | GUI `offscreen` setup passed; does not validate Windows |
| Copy without uv or Python in `PATH`, path with spaces and Unicode | Actual uv 0.12.10 download into `.tools/uv`, `.venv` creation and GUI `offscreen` diagnostics passed |
| Repeated setup in that copy | Passed twice; same lock, profile and system uv binary; no receipt or user uv installation |
| Interpreter and packages in that copy | Existing managed CPython and package cache reused; does not establish downloads from empty caches |
| Marker music and catalog files during core setup | Bytes preserved; lock unchanged |
| Actual official Linux VS Code download and extraction | Passed; CLI 1.141.0 run from a temporary folder, without changing system editor or extensions |
| Recommended extensions | Installation and unavailable-extension warnings covered by simulated CLI tests |
| Ruff, formatting and strict mypy | Passed; mypy checked 35 source files |
| Bash syntax and ShellCheck | Passed |
| Wheel and source distribution | Built successfully |
| Workflow | Valid YAML and actionlint 1.7.12 passed |

CI is configured to use the launchers in all eight jobs; Windows uses Windows PowerShell 5.1. Linux and Windows with uv 0.12.10 add initial core setup without uv or Python in `PATH`, repeated twice. **These changes have not yet run on GitHub Actions.** Actual Windows/macOS checks, editor downloads and manual VS Code integration review remain pending. No system packages were installed during local checks: proposals and authorization for such installations are tested with simulations.

## GUI import and catalog creation: October 9, 2026

Implemented the [import plan](docs/import-plan.md): **Import music…** button and
`Ctrl+I`, recursive FLAC/MP3 folders, `.tfo` creation or open-catalog updates,
progress, cancellation and issue reports. The core remains independent of Qt.
Schema, dependencies and `uv.lock` were unchanged.

Local checks on Linux x86-64, glibc 2.44, Wayland, uv 0.12.10,
CPython 3.13.15 and PySide6 6.11.2:

| Check | Observed result |
| --- | --- |
| Complete suite with GUI | **291 passed, 4 skipped**; all four skips require PowerShell, absent on this machine. |
| Ruff and formatting | Passed; 68 files checked for formatting. |
| Strict mypy | Passed on 39 source files. |
| Core from installed wheel outside the checkout, without PySide6 | **247 passed, 8 skipped**; four GUI modules skipped without Qt and four tests without PowerShell. |
| Batches with controlled temporary audio and real Mutagen reader | Creation, reimport, stable IDs, removed fields, artwork and corrupt files checked. |
| Errors and cancellation | Empty/no valid audio, permissions, actual SQLite lock, rollback, unknown destination, exclusive reservation and own-file cleanup checked. |
| GUI and lifecycle | Previous reads finish before writer; second import blocked; selection preserved; partial cancellation, disposal and direct QApplication exit verified with controlled events/timers. |
| Product diagnostics | Passed with `offscreen`, Wayland and session-available `xcb`; imports a temporary FLAC, removes audio and queries the result. |
| Creation through the button on Wayland with real music | Imported a temporary copy of **To War! / Abbath / Abbath / 2016**, track **1/10**, disc **1/1**, genre **Black Metal**, artwork **500 × 500**; original SHA-256 unchanged. |
| Local visual review | Inspected form, result and catalog screenshots on Wayland; minimum-size Qt `offscreen` renders with Unicode and long issues showed no dialog clipping. |
| Wheel and source distribution | Built; contain new modules, dialog, icon, styles and migrations. Verified 12 resource hashes and 54 RECORD hashes. |
| GUI wheel probe from an unrelated directory | `offscreen`, Fusion, events and import passed (`imported=true`). |

The real-music check used a copy in a temporary directory and a new catalog.
Original files and working catalogs were not modified. Validation screenshots
and databases remain outside the repository.

The isolated installation used requirements exported with `uv export --locked`,
hashes and `--no-deps`; the wheel was also installed with `--no-deps`. The
temporary environment was removed. Checkout checks used `uv run --locked --extra gui`.

The existing GitHub Actions matrix includes these tests and verifies modules and
import from the wheel. Cross-platform results after test fixes are recorded in
the October 9 correction section. Manual visual review and actual Windows/macOS
interaction remain pending. `offscreen` results do not establish desktop
behavior; the Wayland/`xcb` backends checked here cover only this Linux machine.

## Unique artists and consolidation: October 9, 2026

Implemented the [artist identity plan](docs/artist-identity-plan.md). Revision
`002_unique_artists` shares each exact name across the catalog and consolidates
previous rows, retaining the lowest ID and all relationships. Historical `001`
snapshot and SQL remain intact. Dependencies and `uv.lock` were unchanged.

Local checks with uv 0.12.10, CPython 3.13.15, SQLite 3.53.1 and PySide6 6.11.2:

| Check | Observed result |
| --- | --- |
| Complete checkout suite, GUI `offscreen` | **335 passed, 4 skipped**; all four skips require absent PowerShell. |
| Ruff, formatting and strict mypy | Passed; 73 files checked for formatting and 42 source files by mypy. |
| Global identity and Abbath → Accept correction | Reuses artists across albums, folders, libraries and tracks without albums; retains IDs and leaves other credits intact. |
| Schema and populated migration | Exact equality, track/album credits, roles, positions, `external_id`, unreferenced artists, BLOBs and original tags checked. |
| Failures and compatibility | Data/index/revision rollback, backup failure, SQLite WAL, concurrent updates, weakened indexes and unknown revisions checked. |
| Opening and form | Reads `001`/`002` unchanged; validation and empty batches do not migrate. GUI integration upgrades when opening the writer and reopens with selection preserved. |
| Historical and current SQL | Both match their online-applied revisions; `002_current.sql` generated from the packaged chain. |
| Consolidation of a real catalog copy | **13 → 2 artists**, Abbath ID 1 and Accept ID 3; all other rows and view values preserved. Valid backup and repeated execution without byte changes or another copy. |
| Working catalog upgraded | `data/database.tfo` at `002_unique_artists`; **139 tracks, 139 files, 13 albums and 139 track credits** preserved. Empty `foreign_key_check` and `integrity_check=ok`. |
| Working catalog backup | `data/database.tfo.001_initial.99fd2fa0fa7442d1b84d67ad03bc0364.bak`, validated against consolidated data. |
| Temporary volume test | Full upgrade with backup of 10,000 artists and 10,000 credits in 0.052 s on this machine; helper index removed after migration. |
| Wheel and sdist | Built and verified outside the checkout, with current schema and migration `002`. |
| Core against installed wheel, without PySide6 | **290 passed, 8 skipped**; four GUI modules and four PowerShell tests skipped. |
| CI wheel verification block run locally | Generation, import, reimport and upgrade from `001` with backup and idempotence passed. Locked dependencies with hashes. |
| GUI diagnostics | Product passed on `offscreen` and Wayland; GUI wheel passed on `offscreen`, with Fusion, events and import confirmed. |

The real-catalog comparison covered all tables and the view, including artwork
and `raw_tags`; only duplicate artist rows, their references and the revision
changed. Migration neither rereads nor writes music. Catalog and backup remain
excluded from Git. GUI credit editing is still pending; correction was verified
by reimporting corrected metadata.

The cross-platform matrix includes new modules and wheel verification.
Windows/macOS results are in the next section. Manual visual review remains
pending; Wayland validates only this machine.

## Cross-platform test fixes: October 9, 2026

[Run 37916069251](https://github.com/Evilchuck666/Trackfolio/actions/runs/37916069251),
on `8a755c8`, passed on Linux and macOS Intel with both uv versions. Windows
failed a core test, while macOS Apple Silicon had GUI integration timeouts.

On Windows, setup for `test_existing_migration_target_disappearing_is_not_recreated`
left its SQLite connection open: the connection context commits or rolls back
transactions but does not close the file. Explicit closure was added to
`test_database.py` connections, retaining commit/rollback, plus a regression
holding a connection reference to verify closure on Linux too.

On Apple Silicon, failures occurred when starting another import after earlier
queries. The same timeout was reproduced locally with `sys.setswitchinterval(0.1)`:
the wait alternating `processEvents()` and `QTest.qWait(5)` prevented workers
from advancing under that scheduling. Waits now use `QEventLoop` and Qt timers,
with the same five-second limit. The reentrant import test covers 0.005- and
0.1-second intervals and restores the previous value. Product code, catalog and
locked environment were unchanged.

| Local check | Result |
| --- | --- |
| Database and import integration tests | **34 passed**. |
| Complete suite, GUI `offscreen` | **337 passed, 4 skipped**; PowerShell absent. |
| Ruff, formatting and mypy | Passed; 73 files formatted and 42 source files checked by mypy. |

[Run 37919647833](https://github.com/Evilchuck666/Trackfolio/actions/runs/37919647833)
confirmed fix `1b68511` on all six Linux/macOS combinations. Windows passed the
core test and reached two previously unexecuted GUI failures:

- The Qt picker returns paths with `/`, while `str(WindowsPath)` uses `\\`.
  The test now compares `Path` objects, preserving path and Unicode checks.
- The old-catalog test stored its root with `str(music)` instead of the
  repository's `music.as_posix()`. The fixture now uses the actual representation;
  ID, artist and one-created/one-updated song expectations remain. Its SQLite
  connections are also explicitly closed.

These changes were published in `5850021`, branch `generate-db`. Its **25 affected
tests**, Ruff, formatting and mypy pass locally.
[Run 37920075123](https://github.com/Evilchuck666/Trackfolio/actions/runs/37920075123),
on `58500218e7b11e22836f7036f593eed3a20a242e`, finished with **all eight jobs passing**:

| Platform, with uv 0.12.10 and 0.12.23 | Core without Qt | Suite with GUI |
| --- | --- | --- |
| Linux x86-64 | 295 passed, 4 skipped | 341 passed |
| Windows x86-64 | 283 passed, 16 skipped | 329 passed, 12 skipped |
| macOS Intel | 295 passed, 4 skipped | 341 passed |
| macOS Apple Silicon | 295 passed, 4 skipped | 341 passed |

Qt modules are skipped in core suites. Windows also skips Unix launchers and the
filename containing `?`, unsupported by that system. None of the corrected tests
were skipped. Ruff, formatting, mypy, `offscreen`/native GUI diagnostics and
installed-wheel verification outside the checkout passed. Manual visual review
on Windows/macOS remains pending.

## Catalog song editing: October 9, 2026

Implemented the [editing plan](docs/edit-plan.md): **Edit**, **Save** and **Cancel**
for the ten detail fields, artists and genres as ordered lists, inline validation
and navigation with pending changes. Corrections are saved in SQLite and work
without the music file. Reimport replaces manual values with file tags; the form
explains this consequence.

The Abbath → Accept correction reuses exact artist identity and changes only the
selected song. Album title/year reassign a grouping without changing other
tracks; shared tracks are copied for the selected file. Audio, artwork,
`raw_tags` and additional roles are preserved. Dependencies, `uv.lock`, historical
revisions and current `002_unique_artists` schema remain unchanged.

Local checks on Linux x86-64, glibc 2.44, CPython 3.13.15, uv 0.12.10,
PySide6/Qt 6.11.2 and SQLite 3.53.1:

| Check | Observed result |
| --- | --- |
| Complete checkout suite, Qt `offscreen` | **426 passed, 4 skipped**; all four skips require absent PowerShell. |
| Core/SQLite editing and use-case cleanup | **48 tests**: partial patches, clearing values, validation, exact identity, isolation, conflicts, rollback, suggestions and `001` backup. |
| GUI coordination with temporary SQLite | **23 tests**: save/reopen, cancel, navigation guards, cooperative closure, conflicts and stale responses. |
| Ruff and formatting | Passed; **82 files** checked. |
| Strict mypy | Passed on **46 source files**. |
| Product diagnostics | Import and editing confirmed on `offscreen`, Wayland and X11 (`xcb`), with Fusion and 12 verified resources. |
| Native Wayland window | Save title and artist through controls, reread SQLite, cancel another draft and retain selection; source catalog and original temporary FLAC unchanged by SHA-256. |
| Screenshot review | Controls inspected on Wayland and renders at 1320 × 840 and 960 × 640; lists, buttons and scrolling available. |
| Wheel and source distribution | Built; new modules and resources included. CI matrix wheel verification block executed locally. |
| Wheel installed without checkout or Qt | Creation, import, use-case editing, reread and migration with backup passed; PySide6 absent. |
| Suite from installed wheel without Qt | **341 passed, 10 skipped**; six GUI modules skipped without PySide6 and four tests without PowerShell. |
| GUI wheel installed outside the checkout | Probe with `events=true`, `imported=true` and `edited=true`, `offscreen` backend and Fusion; edits after audio removal and preserves original tags and artwork. |

Checks used controlled temporary databases and FLAC containers; no personal
music or catalogs were modified. Screenshots were retained outside the
repository. First-save `001` backup, external-change detection and confirmed
results after later cleanup failure have dedicated tests.

Two races were fixed and covered: a refresh response preceding **Edit** no longer
replaces the draft or opens an unexpected dialog; a post-save navigation
continuation is discarded if an observer has already opened another catalog.
New integration waits use Qt's native loop and SQLite connections are explicitly
closed to preserve previous macOS/Windows fixes.

The existing matrix includes the new tests and requires editing in diagnostics
and the installed wheel. The first remote run is in the following section.
Manual visual review on Windows and macOS remains pending. `offscreen` tests do
not establish real desktop behavior; native backends checked in this delivery
cover only this Linux machine.

## macOS editing dialog fix: October 9, 2026

[Run 37935958225](https://github.com/Evilchuck666/Trackfolio/actions/runs/37935958225),
on `60e8948`, passed on Linux and Windows with both uv versions. All four macOS
combinations (Intel and Apple Silicon) failed only
`test_real_unsaved_dialog_cancel_restores_selection_and_draft`: it expected the
“Unsaved changes” title and received an empty string.

[Qt documents](https://doc.qt.io/qt-6/qmessagebox.html#setWindowTitle) that macOS
ignores `QMessageBox` titles. The test now checks the actual dialog message,
“There are unsaved changes to this song.” It still clicks **Cancel** and verifies
that selection and draft are preserved and SQLite remains unchanged. No tests
are skipped and product behavior is unchanged.

Local checks: **39 widget/edit-integration tests passed**; complete `offscreen`
suite **426 passed, 4 skipped** (PowerShell absent); Ruff, formatting of 82 files
and mypy on 46 source files passed.
[Run 37937722182](https://github.com/Evilchuck666/Trackfolio/actions/runs/37937722182),
on `33b6813`, confirmed the fix: **430 tests passed** on all four macOS
combinations (Intel/Apple Silicon, uv 0.12.10/0.12.23). Linux also passed with
both versions. GUI diagnostics and wheel verification passed on all six combinations.

Windows reached another failure in both variants: the save-and-continue-with-
**Refresh** test waited for saving but not refresh completion. It could observe
an intermediate state without pending jobs and exit the loop; when deferred
refresh started, its final condition became false again. The test now also waits
for the detail-loaded signal after **Refresh** and checks that saving produced
a result. The five-second limit remains and product code is unchanged. Event
ordering was reproduced with real Qt and SQLite: the timeout message appeared in
**0.026 seconds** when refresh started before exiting the wait loop. The complete
local suite remains **426 passed, 4 skipped**, with Ruff, formatting and mypy passing.
[Run 37939283014](https://github.com/Evilchuck666/Trackfolio/actions/runs/37939283014),
on `efb9935a9177b509b9bd2962a2f21c46656cc400`, finished with **all eight jobs passing**:

| Platform, with uv 0.12.10 and 0.12.23 | Core without Qt | Suite with GUI |
| --- | --- | --- |
| Linux x86-64 | 345 passed, 6 skipped | 430 passed |
| Windows x86-64 | 333 passed, 18 skipped | 418 passed, 12 skipped |
| macOS Intel | 345 passed, 6 skipped | 430 passed |
| macOS Apple Silicon | 345 passed, 6 skipped | 430 passed |

The six GUI modules are skipped without Qt. Windows retains Unix-launcher and
`?`-filename skips; corrected tests run on every platform. Ruff, formatting,
mypy, native/`offscreen` GUI diagnostics and installed-wheel verification outside
the checkout passed. Manual Windows/macOS visual review remains pending.

## Repository

Git initialized with branch `main`, `origin` and tracking of `origin/main`. Infrastructure and documentation are published in [Evilchuck666/Trackfolio](https://github.com/Evilchuck666/Trackfolio), a private repository. Open the workspace with `code Trackfolio.code-workspace`; setup for another PC is in [README.md](README.md).

## Upgrade to uv 0.13.4 (2026-10-29)

Official `uv` and `uvx` 0.13.4 binaries were installed in `.tools/uv`. The project
requirement changes to `>=0.13.4,<0.14`; launchers read that requirement to select
or download uv. The backend remains pinned to `uv_build==0.12.10` and `uv.lock`
has not changed.

Local checks on Linux with CPython 3.13.15:

- `uv lock --check --offline`: passed with uv 0.13.4.
- GUI setup through `setup.sh`, Qt/Fusion `offscreen` diagnostics, import and
  editing: passed with uv 0.13.4.
- Complete suite with local uv and `QT_QPA_PLATFORM=offscreen`: 426 passed and
  4 skipped because PowerShell is not installed. The GUI suite requires running
  outside the sandbox on this machine.
- Ruff, formatting check and mypy: passed.
- Wheel and source distribution: built with local uv 0.13.4.

The workflow is renamed from `checks.yml` to `release.yml`, with uv 0.13.4 on
all four platforms. Initial Linux/Windows setup checks both local binary
versions. This revision's GitHub Actions execution and manual Windows/macOS
visual review remain pending.

## Batch selection and editing (2026-11-02)

Local validation on GNU/Linux x86-64, CPython 3.13.15 and Qt 6.11.2 with
`offscreen` backend:

- Complete suite: **456 passed, 4 skipped**; all four skips require PowerShell.
- Ruff, formatting and mypy: passed.
- `doctor.py --gui --platform offscreen`: zero errors, including resources,
  catalog import and editing.
- Multiple selection with Ctrl/Cmd and Shift, album/artist/year/genre editing,
  mixed values, explicit clearing and disabled individual fields.
- Saving with real SQLite: changes limited to selection, shared tracks,
  conflict detection before writes and rollback after a later failure.
- Save/Discard/Cancel during navigation, selection retained after save/refresh,
  and editor exit when there are no effective changes.
- Renders reviewed at 960×640 and 1320×840; save actions outside the scrollable
  area and geometry tests preventing clipping of batch controls.

This check does not include a new CI run or native Windows/macOS desktop review
for batch editing.

### Navigation wait after batch saving (2026-11-02)

[Run 41446589402](https://github.com/Evilchuck666/Trackfolio/actions/runs/41446589402)
failed only on Windows in the save-and-change-selection test. Linux and both
macOS platforms passed. The same commit `d7e40ad` had previously passed all four
platforms in [run 41445291706](https://github.com/Evilchuck666/Trackfolio/actions/runs/41445291706).

The test could detect no pending jobs after saving, before deferred navigation
created the detail query. If that query started before the wait loop returned,
the final assertion failed. The same error was reproduced on Linux by controlling
that continuation's delivery with real Qt and SQLite, without exhausting the timeout.

The wait now checks target selection and its `detail_loaded` signal as well as
save completion and pending jobs. The five-second limit remains and a regression
forces the problematic event order. Only tests and this record change.

Local validation: **457 passed, 4 skipped** without PowerShell; Ruff, formatting
and mypy passed. GitHub Actions validation of this fix remains pending.

## FLAC/MP3 tag writing (2026-11-02)

The **Write tags…** action publishes saved selection fields after reviewing
differences and choosing fields/files. The core prepares a full backup, edits a
copy, verifies audio and metadata and publishes per file; afterward it confirms
`raw_tags` and the affected physical timestamp in SQLite without replacing other
corrections. The [usage and recovery guide](docs/tag-writing.md) contains the
exact format matrix, blocked cases and filesystem limits.

Local checks on Linux x86-64, uv 0.13.4, CPython 3.13.15 and Qt 6.11.2:

- Complete suite: **540 passed, 6 skipped**. Four skips require PowerShell;
  the others are native Windows/macOS tests.
- Ruff, formatting and mypy: passed; mypy checked 52 source modules.
- All ten fields and their removals are written and recovered by importing into
  a new catalog. Tests cover aliases, Unicode/lists, dates and partial numbering,
  ID3v2.3/v2.4, multiple USLT frames, artwork, unknown frames and actual
  redistributable silent audio.
- External changes even with identical size/mtime, permissions, links/duplicate
  destinations, unrelated temporary files, corrupted copies and replacement
  failures leave originals intact. Linux extended-attribute preservation checked.
- Journal/SQLite failures after publication leave catalog updates pending. Tests
  cover interruptions at five transitions and actual subprocess exits at two
  points; recovery distinguishes original/result, respects new edits and does
  not rewrite music. A damaged journal does not hide other operations.
- Full disks or disappearing catalogs stop remaining files. Tests cover
  cancellation, responsive closure, partial selection, Save/Discard/Cancel,
  report export and recovery waiting for an active save.
- `offscreen` and X11 `xcb` GUI diagnostics: zero errors, including import,
  editing, tag writing, backup and artwork on temporary samples.
- Wheel and sdist built with the locked backend. The CI check extracted from
  the workflow ran outside the checkout: core without PySide6 and GUI with
  `events=true`, `imported=true`, `edited=true`, `tags_written=true`.
- Preview rendered and reviewed at 700×580 and 860×760 with `offscreen`.

The new matrix runs on branch `codex/tag-write-validation`. Initial runs passed
Linux and detected macOS attribute API and Windows DACL inheritance differences;
these checks were retained and adapters corrected.

[Final run 41497096830](https://github.com/Evilchuck666/Trackfolio/actions/runs/41497096830)
validates commit `5dbc038` with these results:

| Platform | Core without Qt | Suite with GUI | Job result |
| --- | --- | --- | --- |
| Linux x86-64 | 430 passed, 9 skipped | 544 passed, 2 skipped | Passed |
| Windows x86-64 | 418 passed, 21 skipped | 532 passed, 14 skipped | Passed |
| macOS Intel | 430 passed, 9 skipped | 544 passed, 2 skipped | Passed |
| macOS Apple Silicon | Waiting for runner | Pending | Queued |

Seven GUI modules are skipped without Qt. Remaining skips concern other operating
systems and Unix launchers on Windows. Completed jobs pass Ruff, formatting,
mypy, `offscreen`/native diagnostics, builds and installed-wheel checks outside
the checkout, with and without Qt.

Manual Windows/macOS visual review remains pending; `offscreen` and automated
native diagnostics do not replace that review.

### Simplified writing dialog (2026-11-02)

This revision replaces the first delivery's granular selection. The dialog
immediately shows all selected songs, progress output and only **Close** and
**Write tags**. Writing internally computes differences for the ten saved fields
and applies them in one action, including removals. Files without differences
are skipped. An incompatible date is reduced to the saved year and, with
multiple USLT frames, the first version exposed by the reader is updated while
others are preserved.

Reports appear in a pop-up only on error, including individual file issues and
catalog preparation failures. The graphical pending-operation manager and its
startup opening are removed; core backups, journals and recovery contracts
remain available.

Local validation of this revision on Linux, CPython 3.13.15 and Qt 6.11.2:

- **545 passed, 6 skipped**; PowerShell and other-platform native tests account
  for all six skips.
- Ruff, formatting and mypy passed.
- Direct writing of all ten FLAC/MP3 fields, lyric removal, dates, lists,
  numbering and per-song values; full backup verified.
- List visible before any work, progress, unchanged files without new backups
  or pop-ups, exported error report and cooperative closure.
- `offscreen` diagnostics with import, editing and writing: zero errors.
- Wheel/sdist rebuilt and verified outside the checkout, core without Qt and
  GUI probe `tags_written=true`.
- Dialog rendered and reviewed at 640×480: list, output and both buttons visible.

CI results above correspond to `5dbc038` and the previous dialog; they do not
validate this simplification. New cross-platform validation and manual
Windows/macOS visual review remain pending.

### Backup removal after successful writing (2026-11-02)

When all written files and their SQLite observations are confirmed, the batch
has no errors or cancellation and the final journal is saved, the entire
`.trackfolio-backups` directory is removed in each affected folder. This includes
all UUIDs and previous copies inside it. Cleanup waits until batch completion;
no copies are deleted when individual songs are confirmed.

Incomplete batches retain backups. Cleanup failures are included in the report
and offer the export pop-up; deleted backup paths are removed from the result
and remaining paths retained. Directories replaced by other objects/links and
backups in folders outside the batch are not deleted.

Local validation on Linux with CPython 3.13.15 and Qt 6.11.2:

- **554 passed, 6 skipped**; skips cover PowerShell and native Windows/macOS tests.
- Ruff, formatting and mypy passed, including `win32` and `darwin` platform analysis.
- Entire-directory removal with previous UUIDs, two songs in one folder and songs
  in separate folders, after all confirmations.
- Backups retained after partial errors, cancellation, SQLite/journal failures.
  Cleanup failures and directory replacement reported without deleting unrelated data.
- Updated report when one folder is cleaned and another fails; successful retry
  in the same session after manually moving an earlier backup directory.
- GUI `offscreen` diagnostics: zero errors. Probe and wheel check verify absence
  of `.trackfolio-backups` after success.

The workflow is updated to check this result with the installed package.
CI execution of this revision remains pending.

### Write button after completion (2026-11-02)

**Write tags** is disabled when all songs finish confirmed or unchanged, without
errors or cancellation. **Close** remains active. Errors and pending results
allow retrying; after repairing a file and completing that retry successfully,
the button is also disabled.

Local validation: all nine dialog integration tests pass, including a second
click without another write, unchanged files and retry after restoring a missing
file. Ruff, formatting, mypy and GUI `offscreen` diagnostics passed.

### Writing tags for the entire catalog (2026-11-02)

The **Write tags for the entire catalog…** action above the main list queries
all songs in a worker and opens the existing dialog. It includes unselected
entries and entries added after loading the window. It resolves
Save/Discard/Cancel before fetching the list and retains previous selection.
The button is disabled without a catalog, with an empty catalog or during other
operations.

Local validation: **562 passed, 6 skipped**. The 17 dialog tests include actual
whole-catalog writing, new invisible entries, empty selection, drafts, read
failure and safe closure during queries. Ruff, formatting, mypy and GUI
`offscreen` diagnostics passed. Window reviewed at 960×640 and dialog at 640×480.
This revision does not include a new CI run.

### Optional album.nfo updates (2026-11-03)

Implemented the [NFO plan](docs/album-nfo-plan.md) on local branch `update-nfo`.
Application composition adds the XML codec to the writing service. One NFO is
checked per folder, including operations without audio differences; absence
creates neither files nor errors. NFO results are separate from songs in the
dialog, JSON report and version `2` persistent journal. Technical review retains
compatibility with version `1` journals.

Local validation on Linux x86-64 with CPython 3.13.15 and Qt/PySide6 6.11.2:

- **623 passed, 6 skipped**. Skips cover four PowerShell tests and native Windows
  locks/streams and macOS attributes/ACL tests.
- Ruff and formatting passed; mypy passed on Linux and with `--platform win32`
  and `--platform darwin`. `git diff --check` found no issues.
- Real XML with title, year/dates, genres, credits, clearing values, Unicode and
  escaping; preservation of unrelated fields, referenced images, reviews,
  attributes, comments, processing instructions, CDATA and namespaced extensions.
  UTF-8 with BOM, UTF-16 and ISO-8859-1, with CRLF preservation.
- Malformed/unsupported XML, DTD, entities and 16 MiB limit; originals preserved.
  Enriched artists are not reassigned to different identifiers.
- Partial selection aggregates all folder tracks and preserves unselected audio.
  Compilations, contradictory data, uncataloged audio, albums beneath an imported
  root and names with special SQL characters checked.
- Single publication of a shared NFO, NFO-only update, second run without
  replacements, retry after publishing audio and multiple independent albums.
- Concurrent document/catalog/folder changes, NFO appearance/disappearance,
  links, permissions, insufficient space and cancellation checked. NFO failures
  preserve music results and backups; joint success allows cleanup.
- Journal failures before/after publication and actual abrupt subprocess exits
  at two NFO write points; later hash-based review without rewriting.
  Mode and extended-attribute preservation checked on the local system.
- Qt `offscreen` integration: NFO progress/results, separate audio counter,
  pop-up and JSON report, NFO-only retry and final state of both buttons.
- GUI `offscreen` diagnostics: **0 errors**, including import, editing and real
  tag/NFO writing; probe returns `nfo_written=true`.
- Wheel and sdist built with pinned `uv-build==0.12.10`, available in local cache.
  Wheel installed outside the checkout, reusing locked local core dependencies:
  import, editing and audio/NFO writing checked with `PySide6` absent. The local
  Qt distribution was then enabled in that interpreter and the installed-wheel
  GUI `offscreen` probe passed.

The workflow is extended to verify packaged NFO modules and NFO writing from the
installed core and GUI probe. This revision has not been run or published in CI.
Native validation on Windows/macOS and manual desktop visual review remain
pending; `offscreen` does not establish that review.

### Song title fixes in NFO track lists (2026-11-03)

The user's case exposed a scope/test gap: the initial implementation synchronized
general album fields and preserved the entire `<track>` list, so “To War! →
To War!2” did not update `track/title`. A successful NFO result did not establish
that this title had been synchronized.

Snapshots now include title/numbering, and the NFO plan includes title targets
for selected songs. Matching uses `position` and track/album `discnumber` where
present, accepting leading zeros. Missing/ambiguous matches produce conflicts.
Unselected titles, track order, position, duration and unrelated metadata are
preserved. No list is created where none exists. Earlier version `2` journals
without these fields remain
readable and reviewable.

Local validation of the fix:

- “To War! → To War!2” was first reproduced with two failing tests and passes
  after the fix: joint audio/NFO writing and NFO-only correction when audio is
  already updated and there are no general album differences.
- Partial selection, discs sharing positions, missing/duplicate positions,
  clearing titles and preservation of attributes/comments/durations checked.
- **633 passed, 6 skipped** in the complete suite; skips still cover PowerShell
  and native Windows/macOS tests. Ruff, formatting and mypy passed.
- Qt dialog checks NFO title correction with unchanged audio. GUI `offscreen`
  diagnostics verify `track/title` and preserve `track/duration`: **0 errors**.
- Wheel/sdist rebuilt; wheel passes music/NFO writing in an isolated interpreter
  without Qt and GUI `offscreen` probe with the new `track/title` check.

This fix is verified on temporary files; to apply it to an open library, restart
the application and run **Write tags** again. No publication or new CI run;
native cross-platform validation remains pending.

### XML header and artist representation in NFO (2026-11-03)

Writing preserves the original XML declaration, the newline separating it from
content and trailing newlines, respecting LF/CRLF and supported encoding.
A header joined directly to `<album>` is repaired even without music differences.

`albumArtistCredits` is not added to an NFO that lacks it. A direct `artist` is
synchronized if present. When that representation exists, redundant simple
credit blocks from earlier versions are removed; credits with IDs, attributes
or annotations are preserved with their protective checks.

Local validation: **649 passed, 6 skipped**, Ruff, formatting and mypy passed,
and GUI `offscreen` diagnostics reported **0 errors**. Tests cover LF, CRLF,
blank-line separation, UTF-8, UTF-16 and ISO-8859-1, trailing newlines, NFO-only
repair with unchanged audio, simple-block cleanup, enriched-credit preservation
and second-attempt idempotence. Probe checks header separation and absence of
added credits.

To apply the change in an open session, restart Trackfolio and run **Write tags**.
Native validation and a new CI run remain pending.

### Windows and macOS CI failure fixes (2026-11-03)

Attached logs from [run 41619108486](https://github.com/Evilchuck666/Trackfolio/actions/runs/41619108486),
on `05d3a7577ec78eab2a707e3f07e301bf9b9ab614`, were analyzed. Linux passed;
Windows failed core tests and both macOS platforms failed installed-wheel
verification. macOS core/GUI suites did pass.

Identified and corrected causes:

- **Windows, library query:** the repository stores `root_path` using
  `as_posix()`, but the NFO query used `str(root)` with backslashes. The query
  returned no tracks and caused folder-composition conflicts. Storage and
  querying now use the same POSIX representation.
- **Windows, pytest parametrization:** the automatic test identifier for 16 MiB
  of content ended up in `PYTEST_CURRENT_TEST`, exceeding Windows' 32767-character
  limit. This caused setup/teardown errors and a roughly 67 MB log. Cases now
  have short identifiers. Test text files specify UTF-8 to avoid depending on
  runner locale encoding.
- **macOS, path aliases:** the wheel was tested under `/var/...`, while audio
  normalized to `/private/var/...`. The NFO retained the unnormalized path and
  was rejected as a different folder. The root is normalized to locate the NFO
  and compare folders, retaining the original imported root in SQLite queries.

Local validation on Linux:

- **654 passed, 6 skipped**; skips cover PowerShell and native Windows/macOS
  checks. Ruff, formatting and mypy passed, including `win32`/`darwin` analysis;
  `git diff --check` passed.
- Five regressions cover root/ancestor aliases, journal reading and retry,
  Windows representation against SQLite, alias target changes and blocking
  links inside the library. Both alias cases reproduced the conflict before
  the code fix.
- **89 NFO tests** pass with CP1252 simulated as pathlib's implicit encoding.
  The longest NFO case identifier is **110 characters**; the oversized document
  is identified as `oversized`.
- Wheel/sdist rebuilt with locally available pinned `uv-build==0.12.10`. Exact
  workflow verification code extracted from `release.yml` was executed: installed
  core passed without Qt using an aliased temporary root, followed by the GUI
  `offscreen` probe from that wheel outside the checkout.

Changes are on local branch `main`. They have not been published and old-commit
jobs have not been rerun: a new CI run with the fix remains pending.

### UTF-8 exported-report reading in Windows GUI tests (2026-11-03)

The new `logs_112800516057.zip` archive was reviewed. Windows now passed core
tests (**522 passed, 21 skipped**), setup and GUI diagnostics. The GUI suite
finished with **1 failed, 645 passed, 14 skipped**:
`test_gui_nfo_error_exports_report_and_retry_updates_only_nfo` compared a Unicode
path read with locale encoding against the original `Música Ω` path.

The product exporter already writes explicit UTF-8. Both JSON reads in
`tests/test_tag_write_gui.py` lacked it; they are corrected along with NFO fixture
encoding. The export/retry test now runs with UTF-8 and CP1252 as implicit pathlib
encodings to reproduce the Windows failure on Linux too.

The regression was first reproduced on Linux with CP1252, producing the same
character corruption as the log. After correcting the reads:

- **655 passed, 6 skipped** in the complete local suite.
- **109 NFO/GUI tests** pass with simulated CP1252 for text reads/writes without
  explicit encoding, extending the previous NFO-only check.
- All **20 dialog tests** pass; Ruff, formatting, mypy and `git diff --check` passed.

Local fix on `main`, without push. A new native CI run remains pending.

### Embedding artwork when writing tags (2026-11-03)

Implemented the [artwork plan](docs/cover-writing-plan.md) on local branch
`thumbnail`, without creating branches or publishing changes. Usage is in
[Tag writing](docs/tag-writing.md#embedding-artwork).

Writing discovers JPEG/PNG files per folder in a worker; the Qt selector resolves
ambiguous folders before backups or audio/NFO publication. One image is used
automatically; no images or explicit skipping preserve current artwork. Only
front covers are replaced, directly verifying embedded blocks/frames and audio
while preserving other image types. Confirmed observation updates SQLite and
details when the dialog closes. Version 3 journals store sources and fingerprints
without image bytes and still support versions 1/2.

Local validation on Linux, Python 3.13.15 and Qt 6.11.2:

- `QT_QPA_PLATFORM=offscreen .venv/bin/pytest -q`: **695 passed, 6 skipped**.
  Skips cover PowerShell and native Windows/macOS checks.
- **148 NFO/artwork/GUI tests** pass with simulated CP1252 for pathlib reads/writes
  without explicit encoding. New fixtures use explicit UTF-8 and binary
  parameters have short identifiers.
- Ruff, formatting, mypy (Linux, `win32`, `darwin`) and `git diff --check`: passed.
- `scripts/doctor.py --gui --platform offscreen`: **0 errors**. Probe checks FLAC
  front-cover bytes, confirmed SQLite thumbnail and `cover_written`; diagnostics
  reject reports omitting that check.
- Wheel/sdist rebuilt with `uv-build==0.12.10`. Verification code extracted from
  the updated workflow passes from the installed wheel outside the checkout:
  first core without Qt with an aliased temporary root, then GUI `offscreen`
  probe. Both demonstrate embedding with Mutagen.

Regressions cover FLAC/MP3, actual JPEG and PNG, uppercase extensions, artwork-only
writing, idempotence, catalog-only synchronization, partial selection, multiple
folders, skipping and selector cancellation/closure. They include duplicate
front covers, back covers and conflicting APIC descriptions, ID3v2.3/v2.4,
encoded-audio hashes, invalid/read-only sources, size limits, links and aliased
roots. Source/inventory/SQLite changes, alias retargeting, insufficient space and
pending-catalog recovery without the source are checked. One regression prevents
`album.jpg` fallback from masking failed embedding; another prevents using SQLite
or NFO as an implicit source.

| Environment | Implementation status |
| --- | --- |
| Linux tests and GUI `offscreen` | Passed locally. |
| Linux installed wheel without Qt and with GUI | Passed locally. |
| Windows | Type analysis and CP1252 simulation passed on Linux; native CI pending. |
| macOS Intel/ARM | Type analysis and alias regressions passed on Linux; native CI pending. |
| Actual graphical desktop | Manual visual review pending; `offscreen` does not establish desktop behavior. |

No new remote CI run or push was performed.

### Album view (2026-11-03)

Implemented locally on active branch `album-view`, without creating branches or
publishing changes. Usage and rules are in [Album view](docs/album-view.md).

The new tab queries SQLite through four lightweight data queries, without reading
music or loading artwork/lyrics for the entire library. Details fetch catalog
artwork when selecting an album. Grouping uses library, folder, title, year,
date, album artists and total discs; numbered disc subdirectories are recognized
only when matching metadata. Compilations retain their track performers.

The editor applies only checked fields: album, year, album artists and genres.
It reuses batch-edit validation, snapshots and transactions, preserving other
songs and edits. Album artists are written as `ALBUMARTIST`/`TPE2`, separate from
`ARTIST`/`TPE1`. Loading older journals normalizes the new list value without
requiring a SQLite schema migration.

The existing writing dialog receives all album tracks and retains per-folder
artwork rules, optional NFO, backup and recovery. Navigation protects drafts with
Save/Discard/Cancel. Stale jobs cannot open an album editor over another selection
or redirect a later song edit. Search remains available during detail loading.

Local validation on Linux, Python 3.13.15 and Qt 6.11.2:

- Complete suite: **722 passed, 6 skipped**. Skips cover PowerShell and native
  Windows/macOS attribute/lock checks.
- **193 passed, 2 skipped** for albums, album GUI, tags and NFO with simulated
  CP1252 for pathlib operations lacking explicit encoding.
- Ruff, formatting, mypy for Linux/Windows/macOS and `git diff --check`: passed.
- GUI `offscreen` diagnostics: **0 errors**. Probe now checks the album tab,
  tracks, artwork and actions; doctor and CI require `albums_viewed`.
- Wheel/sdist built with `uv-build==0.12.10`. Updated workflow verification code
  passes with the installed wheel outside the checkout: album queries and music
  writing without Qt, followed by GUI `offscreen` probe.
- Qt layout screenshot inspected with sample data: navigation, search, artwork,
  common data and track table. This is not a native desktop test.

New regressions cover compilations, multiple libraries/editions, multiple discs,
folders without reliable numbering, queries without music, track-artist
preservation, conflicts with complete rollback, FLAC/MP3 writing of full album
artist names and clearing them, editing without touching audio, all-track/NFO
writing, drafts and actual keyboard shortcuts. They include navigation during
editor loading and invalid years that must not partially save an album.

Native Windows/macOS and actual graphical desktop checks remain pending for this
new view. No push or remote CI execution was performed.

## English translation completed (2026-11-04)

Completed the project-wide translation on the active local `translate` branch.
Application labels, dialogs, accessibility text, errors, command-line help,
setup/diagnostics, README, working/contribution guidelines, design plans,
resource documentation, workflow messages and VS Code tasks are in English.
Historical validation results and CI references remain intact. Unicode music
metadata and path fixtures remain multilingual to retain encoding coverage;
existing accepted input aliases and folder-name recognition remain compatible.

Tests now assert the English messages. Album search uses actual titles and artist
names so translated missing-artist placeholders cannot produce false matches.

Local verification on Linux with CPython 3.13.15 and Qt 6.11.2:

- `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q`:
  **747 passed, 6 skipped**. Four skips require PowerShell; the other two require
  native Windows file locks/streams and macOS attributes/ACL support.
- Ruff and formatting: passed on all 120 Python files.
- Strict mypy: passed on 66 source files for Linux, `win32` and `darwin`.
- Core and GUI `offscreen` diagnostics: **0 errors**, including resource hashes,
  import, editing, tag/artwork/NFO writing and album/artist views.
- Local links and anchors in all 20 Markdown files, VS Code task/debug references,
  Bash syntax and `git diff --check`: passed.

These are local results. No new remote CI run or native Windows/macOS visual
review was performed for this translation. Changes have not been pushed.

## Song search and filters (2026-11-04)

Implemented on the active local `search` branch. The Songs tab combines
case-insensitive title/artist/album search with genre and year filters, including
missing metadata, a matching/total count and Clear filters. Song summaries now
include genres through a second bulk query, without loading artwork, lyrics or
raw tags. No schema migration is required.

Filtering retains matching selections and excludes hidden songs from selected
operations. Save/Discard/Cancel protects drafts; a failed save preserves both the
draft and previous filters. Refresh retains filters, changing catalogs resets
them, and successful edits reapply them. Whole-catalog tag writing remains
independent of filtering.

Local Linux validation:

- Complete Qt `offscreen` suite: **756 passed, 6 skipped**. Skips require PowerShell
  or native Windows/macOS file metadata support.
- Ruff, formatting (121 Python files), strict mypy (66 source files) and
  `git diff --check`: passed.
- GUI `offscreen` diagnostics: **0 errors**, including all 18 resource hashes.
- Inspected an offscreen render at 960 × 640; search, genre/year selectors and
  Clear filters fit within the song panel.

No remote CI or native Windows/macOS visual review was performed for this change.
