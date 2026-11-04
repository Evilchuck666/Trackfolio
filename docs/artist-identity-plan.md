# Plan for catalog-wide unique artist names

Status: implemented October 9, 2026. This document preserves the delivery design; executed checks are recorded in [VALIDATION.md](../VALIDATION.md).

## Agreed rule and result

Each artist name identifies one entity across the catalog. All its songs/albums share `artist_id`, including across folders/libraries. This replaces reuse limited to the current album.

Names are compared exactly, like current genre reuse. Preserve read text: no case conversion, whitespace removal, fuzzy search or aliases. `Accept` and `ACCEPT` remain distinct. Identity is determined by `name`; `external_id` stays optional.

Correcting a song from **Abbath** to **Accept** resolves Accept's unique ID and replaces that song's credit. Abbath's identity/name remain for other credits. [GUI song editing](edit-plan.md), implemented as a subsequent delivery on October 9, already supports this.

## Verified working-catalog state

`data/database.tfo` was inspected read-only:

| Data | Before migration | After `002`, verified |
| --- | --- | --- |
| Revision | `001_initial` | `002_unique_artists` |
| Artists | 13 rows | 2 rows |
| Abbath | 2 rows, IDs 1 and 2 | One row, ID 1 |
| Accept | 11 rows, IDs 3–13 | One row, ID 3 |
| Albums | 13 | 13, same IDs |
| Songs and files | 139 and 139 | 139 and 139, same IDs |
| Track and album credits | 139 and 0 | Same counts, roles and positions |

All sample `external_id` values were `NULL`. This table records the design baseline; migration verification is in `VALIDATION.md`. Migration does not modify music files.

## 1. Current schema and uniqueness

Add Alembic revision `002_unique_artists` after `001_initial` and global unique index `uq_artists_name` on `artists.name`. The index guarantees uniqueness without rebuilding `artists` or its SQLite relationships.

Create `src/trackfolio/infrastructure/schema.py` for the current schema/revision. Derive tables by copying initial snapshot metadata and adding the index. Runtime modules use this current schema.

Keep `migrations/initial_schema.py`, `versions/001_initial.py` and `migrations/001_initial.sql` intact. New installations execute `001` then `002`; existing catalogs use the new revision.

Shared schema validation checks revision, structure, view and the expected unique index: global, without `WHERE`, on `name` with exact (`BINARY`) equality. A file marked `002` without this guarantee is incompatible. Unknown future revisions/unrelated databases remain rejected.

## 2. Consolidating existing data

Run the entire migration in one transaction:

1. Group `artists` by exact name; choose `MIN(id)` as canonical ID.
2. Keep canonical `external_id`; if `NULL`, use the group's first non-null value by ID, if any.
3. Redirect duplicate `track_artists.artist_id` and `album_artists.artist_id` to the canonical ID.
4. Delete only redundant artist rows, including uncredited ones. Retain uniquely named artists.
5. Create the unique index and record `002_unique_artists`.

Credit primary keys are owner, role and position. Changing `artist_id` preserves rows, roles and order. Do not delete credits or renumber positions, or change albums, tracks, files, artwork, genres, lyrics or `raw_tags`.

Use reproducible SQL so the revision can also generate offline SQL. Do not merge through GUI row iteration or music reads. Canonical choice is deterministic from existing IDs; repeating the upgrade does not change it.

Before upgrading an existing catalog, create a consistent SQLite API backup with an independent filename without overwriting another copy. Backup failure prevents migration. Consolidation/index failure rolls back the entire transaction, including Alembic revision.

Repeating on `002` neither creates a copy nor changes data. Downgrade removes the index and permits the old schema; restoring original duplicates requires the backup, since consolidation cannot be reversed by reconstructing IDs.

## 3. Importer reuse

Simplify [`_artist_id`](../src/trackfolio/infrastructure/catalog.py):

- Accept only connection and name.
- Search all `artists` by exact name equality.
- Reuse the ID or create the artist if absent.
- Remove album, library and directory context from the search/calls.
- Keep per-file caching and `_unique_labels` exact credit deduplication.
- Use the unique index for concurrent insertions: `ON CONFLICT(name) DO NOTHING`, then retrieve ID by name within the transaction. Keep bounded waits.

Track and album artists share IDs when names match; relationships, roles and positions remain separate. Album grouping is unchanged: distinct editions/folders can hold different albums sharing artists.

Reimport preserves `file_id` and `track_id`. The **Abbath → Accept** test reimports the same song with corrected credit and verifies Accept reuse without creating another artist, renaming Abbath or changing other songs' credits. Keep album metadata/`album_artists` unchanged to isolate track-credit correction. Stored original tags update from the read file under normal reimport behavior.

## 4. Compatibility and upgrade execution

Before this delivery, `database.py`, `session.py` and `migrations/env.py` imported `001` revision/metadata; `import_target.py` migrated only new catalogs. Adapt entry points together:

| Entry point | Intended behavior |
| --- | --- |
| `open_catalog` | Read recognized `001`/`002` catalogs without modifying/migrating them |
| `SqliteImportTargetFactory.validate` | Validate both schemas without writes, backups or migration |
| `SqliteImportTargetFactory.open(update)` | After GUI queries close, back up/migrate `001` before writing; then check current schema |
| `open(create)` / `migrate_database` | Create through current Alembic revision; upgrade recognized existing databases |
| Individual import script | Keep arguments; `migrate_database` uses the same upgrade |
| Upgrade without importing music | Extend `python -m trackfolio.infrastructure.database` with `--upgrade <catalog>` for explicit backup/migration |

Writing requires `002` and its unique index. Avoid alternate paths writing artists under the old schema. Share validation, backup and migration across entry points; preserve `rw` when updating existing files so disappearance cannot create an empty replacement.

Import retains lazy writer opening: no valid audio or cancellation before opening leaves old catalogs at `001`. The explicit command consolidates without rereading 139 music files. Import completion reopens the reader through the existing lifecycle.

Keep `initial_schema_sql()` and historical `001` export. Add a separate full-current-schema export, such as `migrations/002_current.sql`, through the same Alembic chain. Document that full SQL creates a new database; populated catalogs use online migration.

## 5. Tests and acceptance criteria

- Same names share IDs across albums, directories, roots/libraries and albumless songs; new names create one row.
- Track/album credits share identity where applicable while preserving roles, multiple artists and order. Different names retain separate entities.
- Existing contextual catalog test expects **2 albums and 1 artist**, with unchanged files/original tags.
- Repeated import preserves IDs/artist count; **Abbath → Accept** reuses Accept and preserves other credits.
- The index rejects a second exact name even through direct insertion; two writers respect uniqueness.
- Populated temporary `001` consolidates to `002`: retain `MIN(id)`, both credit tables' rows/roles/positions, `raw_tags` and BLOBs.
- Cover present/absent canonical `external_id` and unreferenced artists.
- `PRAGMA foreign_key_check` returns no rows; `integrity_check = ok` after merge.
- Backup failure or injected failures after credit redirection/before index creation leave old data/revision usable.
- Migration is idempotent; backup retains the old catalog and downgrade removes only the new guarantee.
- Reading `001`/`002` preserves bytes; import forms do not migrate; writer opening upgrades `001`; unknown revisions or `002` without index are rejected.
- Separate historical `001` SQL tests from current-schema tests: `test_export_matches_migrated_schema_and_committed_artifact` currently compares initial schema to `head`.
- Installed wheel outside checkout includes current schema/revision `002` and correctly generates, migrates and imports with Qt-free core and GUI.

Modify `tests/test_catalog.py`, expand database/session/destination/GUI integration tests and add `tests/test_artist_migration.py`. Automated checks use temporary databases. Before upgrading the working catalog, consolidate a copy and verify the baseline table above.

## 6. Implementation order and delivery

| Phase | Files/work | Verifiable output |
| --- | --- | --- |
| 1. Current schema | New `infrastructure/schema.py`, shared validation, separate `001` snapshot | Known schemas recognized; historical export stable |
| 2. Migration | New `versions/002_unique_artists.py`, backup and atomic upgrade | Populated copy consolidated; IDs/credits preserved; rollback tested |
| 3. Importer | `infrastructure/catalog.py`, global reuse tests | Multiple discs produce one row per name; Abbath → Accept passes |
| 4. Entry points | `database.py`, `session.py`, `import_target.py`, `migrations/env.py`, upgrade command | Compatible reads; all writes use `002`; upgrade without music |
| 5. Delivery | Current SQL, workflow, docs, installed package, validation | Tests, Ruff, formatting, mypy and diagnostics pass; results recorded |

Update `.github/workflows/release.yml` to package current schema/revision `002` and replace literal `001_initial` expectations for wheel-created databases. Retain the current matrix/locked environment without new dependencies.

Update `docs/database.md` for uniqueness/upgrades, `docs/architecture.md` for snapshot/current-schema separation, README for the migration command, and `docs/import-plan.md`/`VALIDATION.md` for actual status.

Delivery ends when new imports enforce uniqueness and existing catalogs consolidate while preserving related data. Record local checks, CI runs and pending visual reviews separately.
