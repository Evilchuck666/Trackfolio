# Plan for embedding thumbnails when writing tags

Status: implemented locally on November 3, 2026 on branch `thumbnail`, without creating branches or publishing changes. Validation and pending CI/desktop work are in [VALIDATION.md](../VALIDATION.md#embedding-artwork-when-writing-tags-2026-11-03).

## Expected result

Clicking **Write tags** in the selection or entire-catalog dialog searches each target song's folder for images and embeds the chosen image as the front cover in FLAC/MP3, replacing any existing front cover. This also works without text-tag differences. **Save** continues to save catalog edits without modifying music.

| Images found in the folder | Behavior |
| --- | --- |
| None | Write applicable text/NFO changes and preserve the embedded cover or its absence |
| One | Use automatically, even when another cover is embedded |
| Multiple | Ask which image to use before file publication; one choice per folder shared by its target songs |

Recognize `.jpg`, `.jpeg` and `.png` with case-insensitive extensions. A single PNG is as automatic as a single JPG. Multiple images do not silently favor `album.jpg`, `folder.jpg` or another name.

Search only the audio folder, without traversing subfolders or parents. Neither the SQLite thumbnail nor an NFO `thumb` reference substitutes for a source image. Read the original without modifying or renaming it. Do not download images or convert between JPEG and PNG.

## Image selection and cancellation

1. Resolve pending drafts through Save/Discard/Cancel, as now, and freeze target song IDs.
2. Scan folders in a worker, grouping by physical directory and normalizing aliased roots under the same rules as NFO writing.
3. For folders with multiple images, show a Qt dialog listing filenames, previews and dimensions. Require an explicit selection per folder or allow **Keep current cover** to skip that folder's image.
4. For catalogs with many folders, collect choices in one folder-organized dialog. Do not ask per song or block the worker waiting for Qt.
5. Confirm choices and prepare text, image and NFO writing. Revalidate inventory and selected files before publication.

Cancelling or closing the selector cancels the whole attempt before backups or music/NFO publication. Retry remains available from the main dialog. During scanning and publication, **Close** retains existing cooperative cancellation. Cover choices apply to that attempt only; no implicit preferences are saved for future operations.

Partial selection embeds images only in target songs. Unselected tracks in the same folder are not written. NFO album aggregation still queries necessary tracks without expanding the music selection.

## Meaning of replacing the thumbnail

The chosen image replaces pictures marked **front cover**, leaving exactly one front cover. Back covers, booklets and other picture types retain their bytes, attributes and descriptions. If only another picture type existed, add the chosen front cover and prioritize it in the reader.

| Format | Proposed write |
| --- | --- |
| FLAC | Front `PICTURE` block with original image bytes and MIME/dimensions; preserve other blocks and images |
| MP3 | Front `APIC` frame retaining the supported ID3 version; avoid description collisions with other picture types |

These representations match Mutagen's [FLAC Picture](https://mutagen.readthedocs.io/en/latest/api/flac.html#mutagen.flac.Picture) and [ID3 APIC](https://mutagen.readthedocs.io/en/latest/api/id3_frames.html#mutagen.id3.APIC) APIs. Audio is not re-encoded. Existing restrictions on ID3 versions and files that cannot be verifiably preserved remain.

If exactly one front cover already has the same bytes and MIME, the file need not be replaced solely for that image. Duplicate front covers do require normalization. A second attempt without further changes is idempotent.

**No image** and **Keep current cover** mean no cover-change request, never a deletion request. Represent this explicitly in the domain, distinct from an empty image.

## Source preparation and checks

Add a Qt-independent image discovery/reading adapter. Reuse JPEG/PNG recognition from `infrastructure/metadata.py`, extracting a shared helper if useful. Detect actual content type and dimensions rather than trusting extensions. The GUI checks preview decoding and flags images it cannot display.

Propose a maximum of **15 MiB per image**, also ensuring the resulting block/frame fits its format. Empty, unreadable, unsupported or oversized images are issues, not empty-folder results, and must not erase an existing cover. Users may choose another image or skip that folder's cover. If the only image is unusable, block that folder's songs for the attempt; other folders may continue. Folder scan failures are also issues, not zero-image results.

Record selected image path, identity, size, timestamp and SHA-256. Freeze bytes so all songs in a folder receive the same content. Revalidate the source before each publication: changes, disappearance or replacement cause a conflict and preserve unpublished songs. If inventory changes between scanning and selection, resolve it again without automatically choosing another file.

Accept normalized imported-root aliases and retain their POSIX spelling in SQLite queries. Do not follow image/internal-directory symlinks or junctions, or allow paths outside the imported root.

## Integration with recoverable writing

Artwork belongs in the same plan and replacement as each song's text tags. Do not perform a second direct save on the original after the writer finishes.

1. Add a cover intent separate from `EDIT_FIELDS`: preserve, use selected image or already matching. Artwork differences alone make a song writable.
2. Create a complete backup and audio temporary using existing primitives.
3. Write text and artwork changes into that temporary.
4. Reopen and directly inspect `PICTURE` blocks/`APIC` frames: front type, count, MIME and embedded-byte hash must match the plan.
5. Verify audio hash and unrelated metadata/images. Adapt preservation signatures to allow only the requested front-cover change, without excluding all pictures/APIC frames.
6. Revalidate image source, music original and catalog; sync and publish once.
7. Confirm observed data in SQLite, including embedded artwork, and log the result. Process NFO afterward under existing conditions.
8. Clean up backups only after successful completion of audio/artwork/NFO. Errors, conflicts, catalog-pending states or cancellation retain batch copies.

Verification cannot rely only on `read_metadata(...).artwork`: that reader can return `album.jpg` as fallback even if embedding failed. Bytes must be proven present inside the music file.

Expand space reservation for file growth and backups: artwork repeats in every song even if read once per folder. Reports distinguish preserved, embedded, replaced, already matching and explicitly skipped covers, and show the source path without counting images as songs.

Version the persistent-log extension and accept older versions without cover intents. Store source path, fingerprint and result, without base64 images in `journal.json`. Technical review uses audio hashes/backups and still never automatically restores or rewrites.

## Catalog and displayed thumbnail

Extend the snapshot and `SqliteTagCatalog.confirm`, which currently confirms `raw_tags` and date changes but does not replace catalog artwork.

After successful publication, store/reuse the image in `artworks`, update `cover_artwork_id`, mark source `embedded` and remove that song's fallback path. Refresh details to display the newly embedded cover. Snapshot comparison must also protect concurrent artwork changes.

If audio artwork already matches but SQLite artwork is stale, synchronize only that catalog observation without replacing audio again. Without a selected source, preserve physical artwork and current image data. Confirmation failure after publication remains **catalog pending**.

## Components and execution order

| Phase | Components | Verifiable result |
| --- | --- | --- |
| 1. Contracts and discovery | `domain/tag_write.py`, new image adapter and application ports | Explicit inventories/decisions without Qt or music writing |
| 2. GUI selection | `controller.py`, write dialog and cover selector | Multiple images resolved before publication with safe cancellation |
| 3. Codec and verification | `infrastructure/tag_write.py`, shared image recognition | FLAC/MP3 contain the selected front cover while preserving audio and other images |
| 4. Coordination and catalog | `application/write_tags.py`, `tag_write_catalog.py`, `tag_write_files.py`, `startup.py` | Compatible cover-only writes, backup, confirmation, report and recovery |
| 5. Delivery | Tests, probe, workflow and documentation | Local validation and CI matrix recorded with actual status |

No SQLite schema changes are expected: the image table and per-file references already exist. Keep the core Qt-free and reuse existing dependencies for basic image reading and music writing.

## Tests and acceptance

- Zero images: retain existing covers or absence; never implicitly use SQLite thumbnails.
- One JPG/PNG: automatically embed in FLAC/MP3 with or without prior front artwork, even without text differences; include `.jpeg` and uppercase extensions.
- Multiple images: explicit per-folder choice, previews, multiple folders per operation, voluntary skipping and cancellation before any publication.
- Partial selection: write targets only; share one image among selected songs in a folder and retain separate choices per folder.
- Replace duplicate fronts while preserving backs, booklets, unknown images and potentially colliding APIC descriptions; preserve ID3v2.3/v2.4.
- Read embedded blocks/frames with Mutagen and compare bytes without relying on `album.jpg`, SQLite artwork or Qt previews as proof.
- Unreadable/unsupported images, limits, links, source/inventory changes, Unicode paths, aliased roots and Windows SQLite path spelling.
- Failures before/after publication, insufficient space, cancellation and catalog-pending states; backups retained and retries respect the new choice.
- Idempotence and SQLite-only updates when its thumbnail alone is stale; old-log compatibility and review after actual process interruption.
- Qt worker integration, accessible selector, refreshed details, progress and error reporting; simulated CP1252 execution and explicit fixture encodings.

Update `docs/tag-writing.md`, `docs/tag-write-plan.md`, README and `VALIDATION.md` during implementation. Run Ruff, formatting, mypy, pytest and diagnostics; also validate the installed wheel outside the checkout, first without Qt and then with the GUI. Extend the probe and CI to verify actual embedding, recording Linux, Windows and macOS separately alongside pending manual visual review.
