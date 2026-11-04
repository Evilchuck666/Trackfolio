# SQLite catalog and SQLiteBrowser review

The catalog imports, queries and edits metadata without modifying FLAC/MP3 files. The GUI generates catalogs from folders through **Import music…**; the core also works without Qt. `scripts/import_audio.py` remains an individual preparation/review tool, not Trackfolio's complete CLI.

New catalogs default to Trackfolio's `.tfo` extension. They remain SQLite databases readable by SQLiteBrowser. Existing `.sqlite3`, `.sqlite` and `.db` catalogs can still be opened.

## Tables and relationships

The catalog uses multiple tables. `track_details` joins data for querying; it neither replaces normalized tables nor stores another metadata copy.

| Table | Contents |
| --- | --- |
| `libraries` | Each library's local root |
| `albums` | Provisional album groups: library, directory, title, year, date and disc total |
| `tracks` | Track title, numbering, optional album reference and available lyrics |
| `artists` | Artists shared by unique exact name and optional external identifier |
| `genres` | Genres reused when name text matches exactly |
| `track_artists` | Track artist credits with role and position |
| `album_artists` | Album artist credits with role and position |
| `track_genres` | Track genres with position |
| `audio_files` | Physical file, relative path, format, audio properties and artwork reference/source |
| `artworks` | Image BLOB bytes, SHA-256, MIME and dimensions |
| `raw_tags` | Text tags read per file: key, value and position within the key |
| `alembic_version` | Schema revision applied by Alembic |

Foreign keys connect tables and are enabled on every application connection. Positions preserve artist/genre order. Relationships allow multiple artists/genres per track and album artists different from track artists.

The schema permits one track to reference multiple physical files. The current importer creates one track per new file; it does not yet automatically identify the same recording in FLAC, MP3 or other editions. `track_details` returns **one row per file**; files sharing a track repeat its `track_id`. Credits/genres are aggregated separately to avoid multiplying query rows.

## Identity and missing data

Reimporting the same relative path within the same library updates data and preserves identifiers. A copy at another path or a renamed file is a different file; paths do not establish recording identity.

Albums are provisionally grouped by library, directory and album metadata, including date, year, disc total and album artists. Matching titles alone do not merge them. Missing titles with other album data retain a group with `NULL` title to preserve data and credits.

Each exact name identifies one artist across the catalog. Tracks/albums share `artist_id` across folders/libraries; `uq_artists_name` prevents duplicates. Spaces and case are not normalized: `Accept` and `ACCEPT` differ. Optional `external_id` does not determine identity.

Correcting a song's artist from Abbath to Accept reassigns its credit to Accept's ID, preserving Abbath and other credits. Reimport already applies corrected file tags. The GUI corrects credits through **Edit** and **Save**, with existing-artist suggestions and exact new names. See the implemented [editing](edit-plan.md) and [artist identity](artist-identity-plan.md) plans.

Editing applies only changed fields and preserves audio, artwork, original tags and additional-role credits. GUI summaries display `artist`-role performers under **Artist(s)**; `track_details` still aggregates all catalog roles.

Changing album title/year from a song reassigns only that track to the resulting group without changing the shared album row. Date and album credits are preserved. The form's disc total is `tracks.disc_total`: editing it does not change `albums.disc_total`. If multiple files share a track, editing or reimporting one copies its track and relationships before saving. `file_id` remains but its `track_id` changes; other files retain their data.

Missing scalars are `NULL`. Missing artists/genres create no relationships: Python contracts use empty tuples and the aggregated view shows `NULL`; the GUI displays blanks. Values are not filled from filenames, other tracks or external information.

Year can be extracted from an existing date: `DATE=1981` yields `album_date='1981'` and `album_year=1981`. `raw_tags` retains the original `DATE` tag without inventing `YEAR`. Track numbering is not completed from another record's disc total.

`raw_tags` preserves original text values, including those unused by the catalog. It is not a binary copy of all file structures. Import removes exact duplicates from normalized relationships while retaining read values in `raw_tags`. Changing a catalog entity does not itself rewrite music tags.

**Write tags…** compares saved values with the file and publishes all editable-field differences. Confirmation uses a snapshot including `raw_tags` and updates that observation from the verified read. Physical date changes when writing year also update `album_date`, isolating shared relationships. Other saved corrections, roles and artwork remain intact.

Recoverable logs are outside SQLite at `Trackfolio/tag-writes/<operation>/journal.json` in the user data folder; no tables or revisions are added to schema `002`. Publishing music and confirming SQLite are separate steps. **Catalog pending** retains the written file and requires confirmation review; audio is not rolled back and newer edits are not blindly replaced. See the [recovery guide](tag-writing.md#recovery).

## Artwork

Use recognizable embedded artwork first, preferring front covers. If none is valid, try `album.jpg` in the same directory. If absent or unrecognized, artwork reference/properties remain `NULL`.

Bytes are stored in `artworks.data`; identical images share their SHA-256 entry. `audio_files` records `embedded` or `album.jpg` source, with a relative path for the latter. Artwork remains available in the catalog even if the external file later changes. This phase does not download or generate artwork.

## Import for review

**Import music…** selects a root folder and creates a new `.tfo` or updates the open catalog. Scanning is recursive and selects FLAC/MP3 extensions case-insensitively; the reader verifies actual content. Other files are ignored; symlinks/junctions are not traversed.

Each file uses its own transaction. Unreadable files produce issues and allow continuation; destination failures stop the operation. Cancellation preserves earlier commits and reports pending files. Empty folders or folders without valid audio do not create a new catalog. If one was created but failed before any save, removal is attempted and cleanup failures reported. Existing catalogs are never deleted or overwritten by choosing create-new.

Update rereads every candidate: `file_id` is preserved for the same root/path, and `track_id` while unshared. Previous metadata is replaced, including manual corrections and now-missing fields; additional credits unmanaged by the music reader are preserved. Missing-audio records are not deleted, duplicate recordings are not identified and moved roots are not reassigned. See the [implemented plan](import-plan.md).

From the project root with setup complete, replace example paths with a real file/library:

```sh
uv sync --locked --group dev
uv run --locked python scripts/import_audio.py "/path/to/library/song.flac" --database data/database.tfo --library-root "/path/to/library"
```

The same arguments work with Windows paths. The file must be inside the root. Without `--library-root`, use its directory. The script prepares/recognizes the schema before saving; unrelated databases or unknown revisions are rejected.

Without `--database`, create/update `data/database.tfo`. Explicit paths, including extensions, are respected. This is the local review database. SQLite files/music are excluded from Git. A library root is local: moving the project neither moves music nor automatically adjusts roots in existing databases.

## Upgrade an older catalog

The current revision is `002_unique_artists`. The GUI reads `001_initial` without modifying it. Importing or saving edits creates a consistent SQLite backup and migrates before writing. Preparing/cancelling drafts, saving without changes, validating import forms or importing folders without valid audio do not trigger this upgrade.

To consolidate artists without rereading music, close other catalog-writing applications and run:

```sh
uv run --locked python -m trackfolio.infrastructure.database --upgrade data/database.tfo
```

The command prints the previous-copy path beside the catalog, matching `database.tfo.001_initial.<identifier>.bak`. Existing copies are not overwritten. Backup failure prevents migration; upgrade failure rolls back changes. Repeating on `002` changes no data and creates no backup.

Consolidation retains the lowest ID per exact name and redirects track and album credits. Rows, roles, positions and track/file/album IDs/data are preserved. If canonical `external_id` is empty, take the first non-null value by group ID. Downgrade removes only the index; restoring original duplicate rows requires restoring the backup with the application closed.

Historical [001_initial.sql](../migrations/001_initial.sql) remains intact. [002_current.sql](../migrations/002_current.sql) creates a new database through the current revision; do not run it on populated catalogs. Both are generated from Alembic:

```sh
uv run --locked python -m trackfolio.infrastructure.database --export-sql migrations/001_initial.sql
uv run --locked python -m trackfolio.infrastructure.database --export-current-sql migrations/002_current.sql
```

## Check in SQLiteBrowser

1. Open `data/database.tfo` using **Open Database**.
2. Under **Database Structure**, inspect the tables above and `track_details`.
3. Under **Browse Data**, select `track_details` for combined metadata or a table to inspect relationships.
4. Under **Execute SQL**, run:

```sql
SELECT file_id, track_id, relative_path, format,
       title, artists, album, album_artists, album_year, album_date,
       genres, track_number, track_total, disc_number, disc_total,
       cover_source, cover_mime, cover_width, cover_height, cover_bytes
FROM track_details
ORDER BY file_id;

SELECT file_id,
       album_artists IS NULL AS no_album_artist,
       lyrics IS NULL AS no_lyrics,
       cover_source IS NULL AS no_artwork
FROM track_details;

SELECT id, mime, width, height, length(data) AS bytes
FROM artworks;

SELECT version_num FROM alembic_version;
SELECT name, count(*) FROM artists GROUP BY name HAVING count(*) > 1;
PRAGMA foreign_key_check;
PRAGMA integrity_check;
```

An upgraded catalog reports `002_unique_artists`; duplicate-name and `foreign_key_check` queries return no rows; `integrity_check` returns `ok`. SQLiteBrowser can inspect image BLOBs in `artworks`; the query above checks properties without displaying binary contents.

Expected validation sample:

| Field | Value |
| --- | --- |
| Title / track artist | Run If You Can / Accept |
| Album / date / year | Breaker / 1981 / 1981 |
| Album artist | `NULL` in the view; no `album_artists` rows |
| Genre | Heavy Metal |
| Track / total | 3 / 10 |
| Disc / total | 1 / 1 |
| Artwork | `embedded`, `image/jpeg`, 500 × 500, 385192 bytes |
| Lyrics | `NULL` |

Missing album artist is intentional: the file credits only the track performer. The GUI preserves that absence; import does not infer metadata.

## Canonical migration and reproducible SQL

The schema source is the packaged Alembic migration `src/trackfolio/infrastructure/migrations/versions/001_initial.py` and its `initial_schema.py` definition. The application runs it through `migrate_database`; it does not independently create tables with `create_all`.

`migrations/001_initial.sql` is generated from that revision for inspection and creating new databases in SQLiteBrowser. Regenerate with:

```sh
uv run --locked python -m trackfolio.infrastructure.database --export-sql migrations/001_initial.sql
```

To check only structure, create another empty database in SQLiteBrowser, open the SQL under **Execute SQL** and run the entire script. It includes the transaction, tables, view, Alembic revision and Trackfolio identification marker. It contains no music/sample data and is not run on existing catalogs. This path reviews the same schema as online migration.

During development, `uv run --locked alembic upgrade head` migrates the database configured in `alembic.ini`, default `data/database.tfo`. Future schema changes must be new revisions; initial SQL does not replace migrations of existing catalogs.
