# FLAC and MP3 tag-writing plan

Status: functional implementation dated November 2, 2026, with the simplified flow requested after the first delivery. Local and per-platform checks for each revision are recorded in [VALIDATION.md](../VALIDATION.md). The [usage and recovery guide](tag-writing.md) describes formats and limits. Since November 3, 2026, optional `album.nfo` updates follow the [implemented NFO plan](album-nfo-plan.md). Operations, logs and backup cleanup are shared; NFO results remain separate from music results.

## Result and scope

Edit and save catalog values, select one or more songs, and click **Write tags…**. The dialog immediately shows songs, progress output and only **Close** and **Write tags**.

Writing automatically overwrites every difference between saved editable fields and files. Each song uses its own values; multiple selection does not itself equalize titles, artists or numbering. An empty saved value removes its tag. Files without differences are skipped.

**Write tags for the entire catalog…** uses the same flow for all songs regardless of selection. It obtains the complete SQLite list in a worker before showing the dialog, after resolving pending drafts.

There are no field/file checkboxes, manual difference review, report buttons or pending-operation manager. Errors produce a popup offering a JSON report with results and backups. The list remains visible during preparation, writing and completion, including songs with issues.

**Save** still edits only SQLite. Drafts are resolved with Save/Discard/Cancel before opening the dialog. Selection is frozen; differences are calculated against current files at execution, without stale comparisons or automatically changing targets.

## Field mapping

| Catalog field | FLAC | MP3 ID3v2 |
| --- | --- | --- |
| Song | `TITLE` | `TIT2` |
| Artists | Repeated `ARTIST` values | `TPE1` list |
| Album artists | Repeated `ALBUMARTIST` values | `TPE2` list |
| Album | `ALBUM` | `TALB` |
| Year | `DATE` | `TDRC`, or v2.3 representation |
| Track / total | `TRACKNUMBER` / `TRACKTOTAL` | `TRCK` |
| Disc / total | `DISCNUMBER` / `DISCTOTAL` | `TPOS` |
| Genres | Repeated `GENRE` values | `TCON` list |
| Lyrics | `LYRICS` | First `USLT` version exposed by the reader |

- Write only differences, including front artwork chosen from folder JPEG/PNG files under the [artwork plan](cover-writing-plan.md). Preserve audio, other images and metadata unrelated to the catalog. Without images, retain existing artwork. Do not rename files. Existing adjacent `album.nfo` is synchronized once per folder using consistent values from all cataloged tracks, without expanding music selection.
- Update each modified field's alias family, including reader-recognized `TXXX`, so old values do not take precedence on import.
- Artists and genres retain order, Unicode and complete names, without joining or splitting on commas, semicolons or `/`. Empty lists remove their family.
- Write saved numbers/totals. A total without a number reads back with the number absent, without inventing numbering.
- Changing year preserves valid date precision. Unrepresentable or invalid results become the saved year; clearing year removes the date. Years use four digits, range 1–9999.
- With multiple ID3 lyrics, update the first reader-exposed version, preserving its language, description and other versions. Do not request another selection.
- Preserve ID3v2.3/v2.4; absent tags create v2.4. ID3v2.2, coexisting ID3v1 and lossy v2.3 lists produce issues without conversion.

## Writing a file

Preparation and writing run sequentially in a worker. Before publication, check imported root, permissions, identity, size, `mtime_ns` and complete original SHA-256. Reject symlinks/junctions, hard links, escaping paths and duplicate physical targets.

1. Obtain saved snapshots and internally calculate all differences.
2. Prepare the SQLite writer and persistent operation log.
3. Create a complete exclusive backup and verify its hash.
4. Create an owned temporary file in the original directory and edit that copy.
5. Reopen the copy to verify values, unrelated metadata and audio hashes.
6. Preserve and check platform-specific permissions and attributes.
7. Revalidate original/catalog and log the resulting hash before publication.
8. Sync the copy, replace the original and record the result.
9. Confirm observations in SQLite without reimporting the entire file.

Backups are stored at `<audio folder>/.trackfolio-backups/<operation>/<id>-<name>.tfo-bak`. Temporaries end in `.tmp`; neither is reimported as music. Backups are not hard links. After successful batch confirmation and logging without errors/cancellation, remove the complete `.trackfolio-backups` directory from each affected folder, including all UUIDs. Errors retain copies. Cleanup failures are reported with paths still present. The [guide](tag-writing.md) records platform ACL, attribute and stream limits.

Atomicity is per file, not per batch or across music and SQLite. Revalidation is not a portable compare-and-swap against other music editors. Unverifiable or unpreservable copies are not published.

## SQLite, cancellation and errors

Snapshots include musical values and `raw_tags`. Confirmation compares them transactionally and updates only observations and the affected physical date. It does not replace newer corrections, other records, roles or artwork; shared tracks/albums are isolated where necessary.

`Trackfolio/tag-writes/<id>/journal.json` retains paths, selection, changes, hashes, backups and states. It is written through temporary file, replacement and sync. Publication followed by failed confirmation becomes **catalog pending**; it is not reported as an intact original or blindly restored.

**Close** during work requests cooperative cancellation and waits for a safe point. Published work is retained. Isolated errors allow other files to continue; catalog/log loss and essential storage failures stop remaining work. The window remains responsive.

Output shows per-file results: written, catalog pending, unchanged, not writable, conflict, failed or pending. Errors offer export in a popup; cancellation or error-free completion does not. Logs/backups allow manual recovery. Core `ReviewTagWrites` inspects hashes and confirms observations through contracts; there is no recovery screen or automatic writing/restoration at GUI startup.

## Components and acceptance

| Component | Responsibility |
| --- | --- |
| `domain/tag_write.py` | Requests, snapshots, differences, states, progress and report |
| `application/write_tags.py` | `TagWriteService.execute` prepares all changes and writes; contracts without Qt/ORM/Mutagen |
| `infrastructure/tag_write.py` | Mutagen modification and audio/block/frame verification |
| `infrastructure/tag_write_files.py` | Paths, hashes, exclusive copies, publication, attributes and logs |
| `infrastructure/tag_write_catalog.py` | Partial confirmation with transactional SQLite snapshot comparison |
| `application/album_nfo.py` | NFO preparation, aggregation, publication and review through contracts |
| `infrastructure/album_nfo.py` | XML editing/verification preserving unrelated content |
| `interfaces/gui/tag_write_dialog.py` | Fixed list, progress, two buttons and error-report popup |

Reuse internal preparation, writing and technical review without exposing their granularity in the GUI. Schema `002` and dependencies remain unchanged.

Acceptance verifies:

- Edit → save → write → import into another catalog and recover editable fields.
- Clearing, Unicode, lists, dates, numbering and USLT without unrelated metadata changes.
- Actual audio hashes and preservation of images, blocks, unknown frames and APEv2.
- Failures before/after publication, insufficient space, changed files, permissions, locks, links, cancellation and actual process interruption with durable logs.
- Complete list from opening, direct writing without review, progress output, deferred close and report offers only on errors.
- Ruff, formatting, mypy, pytest, diagnostics, Qt-free core and wheel outside checkout.
- Linux, Windows and macOS Intel/Apple Silicon matrix, separating manual desktop visual review from automatic `offscreen`/native results.
