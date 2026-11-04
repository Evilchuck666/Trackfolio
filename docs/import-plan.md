# Music import and catalog creation plan

Status: functional implementation completed and checked locally on October 9,
2026. CI validation of this delivery and visual review on Windows/macOS remain
pending; see measured results in [VALIDATION.md](../VALIDATION.md).

## Expected outcome

The **Import music…** action selects a folder and builds a catalog from its FLAC/MP3
files, including subfolders. It also adds or updates that folder's music in the
open catalog. When finished, the GUI shows the saved data without requiring
scripts or SQLiteBrowser.

The core coordinates scanning, metadata reading and persistence through Python
contracts independent of Qt. The GUI collects the request, presents progress and
shows the result. Music files are read without modification.

## Verified starting point

| Existing component | Reused or extended behavior |
| --- | --- |
| [`ImportAudio`](../src/trackfolio/application/catalog.py) | Individual import and root containment validation. Folder coordination is missing. |
| [`read_metadata`](../src/trackfolio/infrastructure/metadata.py) | Content-based FLAC/MP3 reading, original tags, missing data and embedded artwork or `album.jpg`. |
| [`SqliteCatalogRepository`](../src/trackfolio/infrastructure/catalog.py) | Per-file transactions and library/path updates that preserve identifiers. |
| [`migrate_database`](../src/trackfolio/infrastructure/database.py) | Canonical schema creation through Alembic and rejection of unrelated databases. |
| [`open_catalog`](../src/trackfolio/infrastructure/session.py) | Read-only opening to query the result. |
| [`CatalogController`](../src/trackfolio/interfaces/gui/controller.py) | Asynchronous jobs, stale response rejection and selection preservation. |
| [`scripts/import_audio.py`](../scripts/import_audio.py) | Individual tool that must retain its arguments and use shared rules. |

The current write operation queries full details again after committing. Batch
import needs a lightweight result to avoid reloading artwork and distinguish a
confirmed write from a later read error. Current shutdown uses `waitForDone()` on
the GUI thread: that lifecycle needs adapting for long imports.

## 1. Scope and rules for the first delivery

- One root folder per operation, scanned recursively. Select regular files with
  a `.flac` or `.mp3` extension, case-insensitively. The reader checks actual
  content; a corrupt file with that extension produces an issue. Ignore other
  extensions, even if their files contain recognizable audio.
- Normalize and validate the root before preparing the destination. Catalog
  paths remain relative to that root, following existing import rules.
- Do not follow file/directory symbolic links or junctions that could introduce
  another root or cycles. Check root containment again during import in case
  the tree has changed since scanning.
- Deterministic relative-path order. Enumerate paths before importing; keep the
  candidate list in memory without preloading metadata or images.
- **Create catalog** uses a new destination, with `.tfo` as the suggested
  extension. Reject an existing path; creation must reserve it exclusively to
  prevent overwriting even if it appears after form validation.
- **Use open catalog** adds new files and updates previously imported ones.
  Validate that it is still a compatible, writable Trackfolio catalog. Retain
  the extension of any existing catalog accepted by the viewer.
- Reread every candidate on every import. The same root and relative path retain
  `file_id` and `track_id`; metadata removed from the file is also removed from
  its record. The updated count includes files reread without changes.
- Another root, a copy or a rename counts as a new location. Do not merge
  recordings by title, tags, format or content. Selecting a subfolder as a
  different root is not equivalent to reimporting the original root.
- Do not delete records for missing files or clean up unreferenced entities.
  Retain existing rules for albums, artists, genres and artwork, missing values
  as `NULL`/empty tuples and their blank presentation.
- Sequential import and one writer per window. Selecting individual files in
  the GUI, simultaneous roots, folder watching, fingerprints to skip unchanged
  files, tag editing and duplicate detection are deferred to later deliveries.

This scope uses the current schema. It requires no changes to `001_initial`, the
exported SQL or `migrations/env.py`. Future columns or history will require a new
Alembic revision.

The subsequent [unique artists by name](artist-identity-plan.md) delivery is
implemented: it replaces contextual artist reuse and adds revision `002` to
consolidate existing catalogs. The paragraphs above describe the original import
scope.

[Tag writing](tag-write-plan.md) adds an explicit action separate from importing
and saving. Backups end in `.tfo-bak` and temporary files in `.tmp`, so the
FLAC/MP3 scanner does not import them. Reimporting after writing reads published
fields; corrections retained only in SQLite are replaced by file values under
the rules above.

[Song editing](edit-plan.md), also implemented, adds isolation when several files
share a track: editing or reimporting one preserves `file_id` and copies its
track, so `track_id` may change. Import preserves additional role credits that
the music reader does not manage; read metadata still replaces catalog values,
including manual corrections.

## 2. Core use case and contracts

Create `application/import_catalog.py` with the `ImportCatalog` use case. It
accepts a request and injected adapters, returns a report and publishes progress
through a Python callback. Cancellation is checked through a Python contract,
without Qt signals. DTOs are immutable dataclasses. Read and destination errors
are defined in the application layer; adapters translate technical exceptions
into those errors while preserving existing entry-point compatibility.

| Proposed contract | Content or responsibility |
| --- | --- |
| `ImportRequest` | Music root, destination path and `create`/`update` mode. |
| `AudioSource` | Candidate path and path relative to the validated root. |
| `AudioScanner` | Cancellable candidate and scan-issue enumeration. Infrastructure implementation. |
| `MetadataReader` | Existing single-file read contract, with errors translated into application errors. |
| `CatalogImportTargetFactory` | Read-only prevalidation and opening/closing the writable destination when needed. |
| `CatalogWriter` | Save one file's metadata and return a `SaveOutcome`. |
| `SaveOutcome` | `file_id`, `track_id` and `created`/`updated` operation, confirmed by the transaction. |
| `ImportProgress` | Phase, candidates found, known total or `None`, processed, created, updated, failed and current path. |
| `ImportIssue` | Path, stage (`scan`, `read`, `write`, `cleanup`) and presentable cause; no Mutagen/SQLAlchemy exceptions in the contract. |
| `ImportReport` | Destination, `completed`/`cancelled`/`failed` state, final counts, issues and fatal cause if any. |

The report distinguishes scan issues from failed files: an inaccessible folder
is not a processed audio file. After scanning,
`processed = created + updated + failed`; pending candidates are the total minus
processed files. Files ignored because of extensions or links do not increase
failures. A `completed` state may contain issues and must be presented as such.
A candidate write failure counts as failed and processed; if global destination
preparation fails, unsaved candidates remain pending. If scanning is cancelled,
the report indicates that the final total is unknown.

The operation follows this sequence:

1. Validate root and destination without creating or migrating a database.
2. Scan with indeterminate progress and cancellation checks. An inaccessible
   root prevents starting; an inaccessible subdirectory is recorded and allows
   the operation to continue.
3. Publish the candidate total and read candidates individually with the current reader.
4. Open the writer when the first valid metadata is available, check
   cancellation again and save each file in its own transaction.
5. Count confirmed commits only. Emit progress without returning metadata,
   BLOBs or complete song details to the GUI.
6. Close the writer on every exit and return the report, including partial
   progress if the operation is cancelled or fails.

Extract common single-file preparation/writing for reuse by `ImportAudio`.
Retain its public `CatalogEntry` result and existing queries; batch import uses
the lightweight write. Do not query the entire list to determine whether a file
is new: make that decision within the transaction that saves it.

## 3. Failures, cancellation and persistence

| Situation | Expected behavior |
| --- | --- |
| Empty folder or no candidates | Show that no FLAC/MP3 files were found. Do not create a catalog or change the visible one. |
| Corrupt, unreadable or missing file | Record the issue and continue with the next file. |
| Inaccessible subdirectory | Continue with the rest and show that scanning was incomplete. |
| Unrelated, incompatible or unwritable destination | Finish with an application error without adopting or overwriting the file. |
| Storage, schema or SQLite lock error | Bounded wait; finish with a fatal cause and confirmed progress. No indefinite retries. |
| Cancellation during scanning | Stop enumeration; do not start importing the partial list. |
| Cancellation during import | Check before reading and before saving; let the active transaction finish and stop before the next file. |
| Cancellation or failure after saving files | Retain completed transactions and show that the result is partial. |

Defer new catalog creation until valid metadata is available. If no write is
confirmed, close resources and attempt to delete only the new file created by
that operation. If cleanup fails, record the issue and remaining path in the
report. Never delete an existing catalog. Once commits exist, the new catalog
remains available even if the result is partial.

Cancellation is cooperative: it does not forcibly interrupt Mutagen, filesystem
operations or transactions. The GUI shows **Cancelling…** until the worker
reaches a stopping point and releases resources. Do not promise instant
cancellation when a file or device is slow to respond.

## 4. GUI flow

Add an **Import music…** button and action, with its own SVG icon, beside **Open
catalog…** and **Refresh**. It must be available without a catalog; the initial
state indicates that users can open one or create one by importing music.

The dialog contains:

- **Music folder**, with a Qt picker and a note that FLAC/MP3 subfolders are included.
- **Destination**: use the open catalog, initially selected when available, or
  create a new one. Without an open catalog, only creation is available.
- **Catalog file**, for creation mode, with a suggested `.tfo` name and a
  user-selected location. The initial directory comes from existing preferences
  or Trackfolio's user data directory, without checkout paths.
- **Import** and **Cancel**. Cancelling the form creates no files or jobs.

When using the open catalog, explain: “New songs will be added and songs
previously imported from this folder will be updated.” During work, indicate
that cancellation preserves data already saved.

Progress shows indeterminate scanning, followed by a `processed/total` bar,
current file and counters. **Cancel** remains accessible. The result combines
created, updated, failed and pending counts with a browsable issue list. Do not
open a dialog for every failed file or present raw technical exceptions.

When a new result contains saved files, open it automatically through the
current reader and remember its path only if opening succeeds. If the destination
was the open catalog, reload the list and details while preserving selection by
`file_id`. Apply this to partial results too; if there were no writes, retain or
restore the previous catalog. An error opening the result must explain that
files were already saved and allow reopening it.

## 5. Asynchronous work and lifecycle

Wire adapters in `startup.py`. The controller receives the import use case or
executor through a contract; it does not import SQLAlchemy, Alembic or Mutagen.
Create, use and release the writable engine inside the import job.
`CatalogSession` remains read-only.

Planned states: idle → preparing → scanning → importing → finalizing → result;
a cancellation request adds the cancelling state. Separate these from the
current query indicator so stale details cannot re-enable actions.

- Disable Import, Open, Refresh and new selections while an import is active.
  Keep the loaded list and details visible.
- Invalidate previous query responses and wait for completion through events,
  without blocking the GUI thread. Retire/close the read session after its last
  job finishes, before starting the writer.
- Translate progress/result callbacks into queued signals identified by
  operation. Update widgets exclusively on the GUI thread.
- Throttle progress to avoid flooding the event queue with a large library;
  the final report always contains exact counts.
- On completion, release the writer before opening/restoring the reader.
  Preserve the previous path and selection during this process.
- When closing during import, request cancellation and defer actual window
  closure. Keep the window, controller and signals alive until workers are
  released. Adapt `closeEvent`, `shutdown`, disposal helpers and
  `interfaces/gui/app.py`: its `aboutToQuit` and `finally` paths must respect
  that order too. Route normal exits through deferred closure and provide final
  cleanup before disposing Qt objects if the event loop has already stopped.
  Do not use the current `waitForDone()` to wait for a long import while the
  window must keep processing events.

## 6. Implementation and verification phases

| Phase | Work | Advancement criterion |
| --- | --- | --- |
| 1. Contracts and rules | Request, progress, report, issues, cancellation and ports in `application/import_catalog.py`; validation shared with individual import. | Use-case tests with test adapters, runnable without Qt or SQLite. |
| 2. Adapters | Scanner in `infrastructure/audio_scan.py`, writable destination in `infrastructure/import_target.py` and lightweight writes in `infrastructure/catalog.py`. | Controlled traversal, created/updated counts, commit/rollback and closure verified with temporary directories and SQLite. |
| 3. Complete orchestration | Wire `ImportCatalog`, read/persistence errors and reusable composition; preserve `scripts/import_audio.py` compatibility. | Importing and reimporting a real temporary FLAC/MP3 folder produces the expected catalog and exact report. |
| 4. Presentation | Button/action, dialog in `interfaces/gui/import_dialog.py`, progress/summary, icon, styles and resource manifest. | QtTest covers source/destination selection, states, cancelled dialogs and result presentation. |
| 5. Asynchronous integration | Import worker/controller, composition in `startup.py`, query suspension, reload and deferred closure. | Responsive GUI, single import, partial cancellation and shutdown without abandoned connections or workers. |
| 6. Delivery | Usage documentation, project checks, installed package and cross-platform matrix. | Recorded results; automated tests and manual visual review identified separately. |

Complete phases 1–3 before connecting writes to the GUI. Phase 4 presentation
can proceed alongside adapters once contracts are settled.

### Cases to verify

- Recursive FLAC/MP3 tree, uppercase extensions, Unicode and spaces; unrelated
  files, links/junctions, empty folders and permission issues.
- Reimport without duplicate paths and with identifiers preserved; removed tags
  and updated relationships; missing files do not delete catalog records.
- Complete, partial and empty metadata, embedded artwork and `album.jpg`,
  original tags and credit order. Reuse existing single-file checks.
- Invalid file followed by a valid one; fatal failure after previous commits;
  rollback of the current file; lightweight result without later BLOB reads.
- Unknown destination or existing creation target, invalid root and no
  importable files: do not alter previous files; verify that no empty new
  catalog remains when none was created or cleanup succeeded, and verify the
  report when cleanup fails.
- Cancellation before starting, while scanning, after reading and after a
  commit; monotonic, exact counts; resources closed on success, error and cancellation.
- GUI → use case → Mutagen reader → SQLite with controlled temporary audio.
  Query metadata and artwork afterward even if the original music is removed.
- Selection preserved on update, visible partial reports and recoverable
  errors; stale queries cannot replace results or re-enable import actions.
- Long-running work controlled with synchronization events: the window
  processes events, cancellation works and closure waits asynchronously.
  Avoid sleep-based tests.
- `QApplication` exit as well as window closure: cancel, release the writer and
  dispose Qt objects in that order, including the `app.py` cleanup path.
- Query sessions still reject writes and the core works without PySide6 installed.

Add tests in `tests/test_import_catalog.py`, `tests/test_audio_scan.py` and
`tests/test_import_target.py`; extend catalog, widget, GUI integration and
shutdown tests. Use only temporary folders, audio and databases.

### Delivery validation

Run Ruff, formatting, mypy and pytest with `uv run --locked`, using the `gui`
extra for GUI checks. Retain core tests without Qt and extend the existing
Windows x86-64, GNU/Linux x86-64 and macOS Intel/Apple Silicon matrix. No new
dependencies are planned; preserve the lock and portable setup.

Check the installed wheel outside the checkout: it must create and open a
catalog using packaged migrations and resources. Manually review folder and
destination selection, progress, cancellation and closure with a real library
chosen for validation. Record OS, architecture and backend; `offscreen` does
not establish interaction or appearance on a real desktop. Windows/macOS visual
review remains pending from the previous phase and must remain explicit until performed.

Update README, `docs/database.md`, `docs/architecture.md`, `docs/gui-plan.md` and
`VALIDATION.md` during implementation. Also correct old `database.md` references
that still describe the GUI as pending. Mark this plan implemented only after
the complete flow and its checks have finished.
