# GUI song-editing plan

Status: implemented and locally validated on Linux on October 9, 2026. Checks and cross-platform review limits are recorded in [VALIDATION.md](../VALIDATION.md). The rest preserves the delivery design.

## Result and scope

Select a song, click **Edit**, change fields and confirm with **Save**. List/details show saved values; closing and reopening retains edits. **Cancel** restores previous values.

The first delivery edits the **SQLite catalog**, working without original music. FLAC/MP3 tag writing needs another adapter and a file/SQLite recovery design and is outside this delivery. The subsequent [tag-writing delivery](tag-write-plan.md) adds independent **Write tags…** to publish modified FLAC/MP3 tags with internal preparation/backups. **Save** still confirms only SQLite; pending drafts are resolved through Save/Discard/Cancel before writing tags.

The edit unit is the selected row's `file_id`. **Abbath → Accept** reassigns that song to existing Accept while preserving other song credits and both artist identities.

| Current field | Editing/representation |
| --- | --- |
| Song | Text; empty becomes `NULL` |
| Artist(s) | Ordered names; existing-artist selection or new names |
| Album | Text; empty removes title while retaining other album data |
| Year | Integer 1–9999, or empty |
| Track number/total | Independently positive integers or empty |
| Disc number/total | Independently positive integers or empty |
| Genre(s) | Ordered names or empty list |
| Lyrics | Plain text preserving line breaks; empty becomes `NULL` |

These are the ten song-detail fields. The later [album view](album-view.md) also edits album artists and publishes them to tags. Date, artwork, paths and technical properties remain unchanged when saving the catalog. Year is explicit catalog data: changing it does not rewrite imported album date.

Batch editing was added later: select multiple `file_id` values and apply album, artists, year and genres through `UpdateCatalogTracks`. The GUI displays common/mixed values and applies only checked fields, including explicit clearing. Title, numbering and lyrics are disabled. The adapter checks all snapshots before writing and saves one transaction, preserving unselected files even with shared tracks/albums. Selection survives saving/refreshing; drafts are protected during navigation, import, catalog switching and close. Global artist renaming and whole-album management remain subsequent deliveries in this original design.

## 1. Editing and validation rules

- Save only changed fields. Distinguish omitted fields from clearing: `None` for scalars, empty tuples for collections.
- Preserve nonempty text, including spaces, case and Unicode. Whitespace-only titles, albums or names are empty. Preserve literal lyrics without HTML interpretation.
- Validate numbers in the core as well as aiding GUI input. Reject nonnumeric text, fractions, zero and negatives. Permit number-only or total-only values. When both exist, require number ≤ total when changing that pair; existing inconsistency does not block unrelated corrections.
- Deduplicate exact artist/genre names, retaining first position. Do not normalize case or add fuzzy identity matching.
- Use list controls for artists/genres with add/remove/reorder. Each entry is a full name; commas/semicolons can belong to names and are not separators.
- Preparing/cancelling a draft does not write data or upgrade schema. Saving unchanged values does not open a writer.

## 2. Qt-independent contracts and use cases

Create `domain/catalog_edit.py` and `application/edit_catalog.py`. Retain existing import/query contracts; do not turn `TrackMetadata` into a form or save drafts with `CatalogRepository.save()`.

| Proposed contract | Responsibility |
| --- | --- |
| `EditableTrack` | Record snapshot: `file_id`, editable values and comparison token |
| `TrackEditPatch` | Changed fields and typed values, including explicit clears |
| `ArtistChoice` | Exact name and optional existing-artist reference |
| `CatalogEditRepository` | Read snapshot, find artists/genres, apply atomic changes |
| `CatalogEditSession` and factory | Open/close existing-catalog edit access |
| `GetEditableTrack` | Load draft values, distinguishing credit roles |
| `FindArtists` / `FindGenres` | Find suggestions without details/artwork |
| `UpdateCatalogTrack` | Validate/persist changes; return confirmed detail/summary |

Use immutable dataclasses, tuples and application errors. The core imports no Qt, SQLAlchemy or Mutagen. The GUI translates text/selections into contracts; `startup.py` injects adapters.

Separate reader/writer factory openings. Drafts/suggestions use read-only connections; only valid effective changes request writing and migration if applicable.

Comparison tokens represent relevant musical values/relationships without BLOBs or ORM objects. Detect external record/album changes while remaining valid after artist-ID consolidation `001 → 002`: compare exact names, roles and positions, not removed duplicate IDs. Resolve names to current IDs on save.

Define recoverable invalid-data, deleted-record, editing-conflict and write-failure errors. Validation errors identify affected fields.

## 3. Persisting an edit

Implement a dedicated adapter such as `infrastructure/catalog_edit.py`, reusing appropriate repository tables/helpers. `SqliteCatalogRepository.write()` also replaces credits, `raw_tags`, artwork and technical properties; it is not the edit operation.

Each save uses one transaction:

1. Open existing catalog with `writable_engine`, URI `mode=rw`, without recreating a disappeared file. Reserve the writer before rereading/comparing the token.
2. Check schema, file existence and snapshot match. External changes cause conflicts before data modification.
3. If files share `track_id`, copy the track and all relationships for the selected file before editing. Preserve `file_id`; `track_id` may change. Other files remain on the original track.
4. Apply scalar changes and resolve affected relationships.
5. Confirm and return consistent detail/summary. Any failure rolls back entities/relationships created in the transaction.

### Artists and genres

Reuse exact-name artist resolution and `uq_artists_name`. Existing Accept uses its ID; a new exact name is created on save with unique-index protection. Do not rename `artists.name` to correct one song or delete unreferenced entities.

Changing **Artist(s)** replaces only the edited track's `artist`-role credits with consecutive positions. Preserve roles such as `composer` and all album credits. Existing detail queries flatten roles; the editor has a dedicated read, while **Artist(s)** and summaries display only `artist`, excluding composers as performers. Other credits remain stored/queryable in `track_details`.

Use the same exact reuse for genres and preserve list order. Do not rewrite relationships whose field did not change.

### Albums and disc total

Many songs may share an album. Changing title/year from a song resolves the resulting group and reassigns only its `album_id`. Do not directly update the shared row or leave stale `import_key` values.

Extract/share `_album_id()` identity calculation: library, directory, title, date, year, disc total and album artists. Reuse matching albums without replacing credits. New albums also preserve noneditable album roles. Incompatible additional credits in an existing group cause a grouping conflict and preserve the draft, without merging data or creating another identical `import_key`.

Displayed disc total is `tracks.disc_total`; editing changes only that selected track value, not `albums.disc_total` or other tracks. Title/year changes retain prior album date, total and credits. Clearing title does not delete an album with other data; if no album data remains, use `album_id = NULL`.

### Schema and older catalogs

Use `002_unique_artists` without new tables: tokens derive from snapshots, not new columns. Preserve revisions/SQL exports. Browsing/preparing drafts on `001_initial` still does not migrate.

First effective save on `001` reuses existing validation, consistent backup and transactional upgrade. Revalidate after migration and display the backup path. Edit failure never partially applies a draft; already committed migration may leave the catalog at `002` with its old backup available. Editing has its own factory independent of import use cases/forms.

## 4. GUI interaction and states

Add **Edit**, **Save**, **Cancel** to details with shortcuts: `Ctrl+E` on Linux/Windows, `Cmd+E` on macOS; standard Save (`Ctrl+S` / `Cmd+S`) through `QKeySequence.StandardKey.Save`; `Escape` to cancel. Keep the table as selector and edit in details. Use shared assets, Fusion styles and Qt controls across platforms.

| State | Behavior |
| --- | --- |
| No selection/loading | Editing disabled |
| Browsing | Read-only fields; Edit available after detail loads |
| Editing, unchanged | Fields enabled, Save disabled, Cancel available |
| Editing, changed | Unsaved-changes indicator; Save enabled for valid data |
| Saving | Draft/navigation locked; “Saving changes…” |
| Error/conflict | Draft preserved, explanation visible; correct/retry/cancel |
| Saved | Return to browsing, refresh summary/detail, retain selection and confirm save |

Retain the draft until transaction confirmation. Cancel discards it and rereads the record, including external changes. Conflicts allow reloading or continuing draft review without automatically overwriting external data.

Song/catalog changes, refresh, import and close first resolve pending changes with **Save / Discard / Cancel**. Save continues the requested action only after success; Discard continues without saving; Cancel retains selection/draft. An unchanged draft exits editing without prompting.

Modify `_selection_changed()`, which currently clears details before notifying the controller. Navigation must consult editing state before clearing; cancellation restores selection with signals blocked.

The controller keeps snapshots/drafts by catalog and `file_id`. Earlier query responses, programmatic field changes and late artist searches must neither dirty the form nor replace active drafts.

## 5. Asynchronous work, close and import

- Run edit reads, suggestions and writes outside the GUI thread. Apply results only in Qt and verify request IDs.
- Keep one writer per window. Before saving, invalidate incompatible queries, wait for completion and release connections. Reuse import's `activeThreadCount()` waiting pattern without blocking Qt.
- Release the writer before querying again. Distinguish confirmed save from later refresh failure: do not report lost edits or automatically write again.
- Defer close during save until its result is known. Never terminate mid-transaction or destroy active worker Qt objects. On failure keep window/draft for the user's decision.

**Reimport:** retain current policy: reread file tags and replace catalog values, including manual corrections. The update form states that file metadata is reread and replaces catalog values. The editor identifies its destination as **Catalog changes**.

Automatically retaining corrections across reimport would need per-field manual-value modeling and a migration; do not implicitly add it here. Editing preserves `raw_tags`; only rereading import replaces them.

Share copy-on-write separation of tracks referenced by multiple files with the import writer so path-specific updates do not affect sibling files. Keep `track_id` in the usual one-track-per-file case; document/test the exception with editing.

## 6. Checks and acceptance

| Level | Required cases |
| --- | --- |
| Qt-free core | Partial patches, explicit clears, numeric validation, ordered exact names, unchanged edits |
| Temporary SQLite | Abbath → Accept reuses ID without affecting other songs; new/multiple artists and other-role credits |
| Relationships | Shared albums, partial album clearing, shared tracks; preserve roles, genres, artwork, audio and `raw_tags` |
| Concurrency/failures | Two editors on one song, deleted records, locked catalogs, permissions, rollback without partial writes |
| Compatibility | No music present; unchanged `001` reads; first save with backup; repeated `002` without new backup |
| Real GUI | Edit/Save/Cancel, field errors, pending-change navigation, close and delayed responses |
| Integration | Save/close/reopen SQLite; list/detail agreement; declared reimport replacement |

Add `tests/test_catalog_edit.py`, `tests/test_edit_gui.py`, `tests/test_edit_gui_integration.py`; expand query/persistence/import tests where behavior changes. Use `Path`, explicitly close SQLite connections and wait asynchronously through a native Qt loop, retaining recent Windows/macOS fixes.

Run Ruff, formatting, mypy and relevant suites with `uv run --locked`. Check Qt-free core, `offscreen` GUI, installed wheel outside checkout and existing Linux/Windows/macOS Intel/Apple Silicon matrix. Update resource manifest/package checks if adding visual assets.

Manually review the real window with a catalog copy/shared album: correct one song, clear values, use multiple artists, check keyboard and cancel changes. Record actual platforms/visual reviews in `VALIDATION.md`, separately from automation. Do not use personal databases for metadata-changing/reimport tests.

## 7. Implementation order

| Step | Delivery | Completion criterion |
| --- | --- | --- |
| 1 | Core values, patch, contracts, validation | Use cases tested without Qt |
| 2 | Dedicated reads, identity resolution, transactional writes | Per-song corrections, relationship isolation and SQLite conflicts tested |
| 3 | Edit factory, `001/002` compatibility, composition | Save without audio; backed-up older-catalog upgrade |
| 4 | Controls, artist/genre lists, draft state | Real-widget Edit/Save/Cancel work |
| 5 | Async coordination, navigation, close, import | No lost drafts/stale responses; explicit per-file reimport |
| 6 | Integration, package, cross-platform matrix, docs | Checks pass with recorded evidence/visual limits |

Update README, architecture and database guide with catalog editing, per-song scope and reimport behavior. Mark implemented only after completing checks.

## Implemented delivery

All six steps have local implementation/tests. Planned domain/application/persistence modules, `ordered_labels.py`, composition and GUI coordination were added. Core/SQLite tests are in `test_catalog_edit.py`/`test_edit_catalog_use_case.py`; widget/coordination tests in `test_edit_gui.py`/`test_edit_gui_integration.py`.

Import shares track copy-on-write and preserves additional track/album roles. GUI queries show performers; SQL views retain all credits. Adapter cleanup failure after commit still reports a saved result with the issue.

GUI diagnostics and wheel validation also test temporary-SQLite editing. [Run 37939283014](https://github.com/Evilchuck666/Trackfolio/actions/runs/37939283014) passed eight Linux/Windows/macOS Intel/Apple Silicon combinations with uv 0.12.10 and 0.12.23. Manual Windows/macOS visual review remains pending; results and test-portability fixes are in [VALIDATION.md](../VALIDATION.md).
