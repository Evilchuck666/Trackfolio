# Tag writing and recovery

**Save** edits the catalog. **Write tags…** publishes all differences between saved editable fields and the selected FLAC/MP3 files, including album artists edited from the [album view](album-view.md). Unsaved changes are first resolved through Save/Discard/Cancel.

**Write tags for the entire catalog…**, above the main list, opens the same flow for every catalog song. It requires no selection and queries the database again in the background, including entries added since opening. It remains disabled without a catalog, with an empty catalog or while another operation is active. The selection-writing action remains available beside song details.

The dialog shows all songs from the moment it opens, progress output, and only **Close** and **Write tags**. Clicking write prepares and verifies changes internally, without field selection or manual difference review. Each song retains its own values; files without text or artwork differences are skipped. Existing `album.nfo` files beside audio are also checked and updated, even if music tags already match. Absence is normal and does not create them. Errors open a popup offering JSON report export; successful operations do not show it.

After successful completion, **Write tags** is disabled and **Close** remains available. Writing is also disabled if all files/NFOs already match or NFOs are absent. Errors or pending work allow retries in the same dialog, including updating only NFO after audio has been written.

## Embedding artwork

Clicking **Write tags** searches for `.jpg`, `.jpeg` and `.png` files in each song's folder, ignoring extension case. Other folders are not searched, and SQLite/NFO are not image sources.

| Images in the folder | Result |
| --- | --- |
| None | Preserve embedded artwork or its absence |
| One | Embed automatically, replacing the previous front cover |
| Multiple | Open **Choose covers** with name, dimensions and preview; require one choice per folder or **Keep current cover** |

All choices are completed before publishing music or NFO. Cancelling the selector cancels the entire attempt; retry is available. The choice is shared by target songs in the folder without writing unselected songs.

The chosen cover is copied with its original bytes and format, without conversion or source modification. JPEG/PNG up to **15 MiB** is supported. Invalid, unreadable or oversized images block that folder's songs; other folders can continue. Source or inventory changes cause an issue and require another attempt. Internal links and linked images are not followed; imported-root aliases are accepted.

Writing leaves exactly one front cover (FLAC `PICTURE` or MP3 `APIC` type 3). Back covers, booklets, other image types and supported ID3 versions are preserved. This also works without text changes. If artwork already matches exactly, audio is not replaced; if only the SQLite thumbnail is stale, the catalog is updated. After successful publication, the detail thumbnail refreshes when the dialog closes.

Reports distinguish preserved, embedded, replaced, matching and explicitly skipped artwork and show its source path. Artwork is verified directly inside the audio and shares the same backup, temporary file and replacement as tags. Failures retain backups under batch rules.

## Optional album.nfo updates

XML with an `<album>` root without a namespace is supported, compatible with Kodi album metadata. `album.nfo` is searched only in the target FLAC/MP3 folder, once per folder. Parent folders are not searched: a shared NFO above disc subfolders is not updated automatically.

Selection determines folders. NFO data comes from every cataloged track in each folder without writing audio outside the selection:

| NFO field | Rule |
| --- | --- |
| `title` | Saved album name, identical across all tracks |
| `year` | Saved year, identical across all tracks |
| Existing `releasedate` | Update year, preserving valid month/day; invalid dates reduce to year. Do not change `originalreleasedate` |
| `genre` | Genre union without exact duplicates, by relative path and each list's order |
| `thumb` | Filename of the cover selected for embedding, even if audio already contains it. Add if missing; preserve without a selected image or when keeping current artwork |
| Existing `artist` or `albumArtistCredits/artist` | Matching album credits; if all are absent, track artists only when identical across every song. Preserve the existing representation without adding absent credit blocks |
| Existing `artistdesc` | Resolved artist names joined with ` / `; no name splitting |
| `track/title` in an existing track list | Saved target song title, matched by `position` and `discnumber` when present on track or album |

Consistent empty values remove managed elements. When album credits are missing and track artists differ, existing NFO credits are preserved, as for compilations. Identifiers belonging to the same artists are preserved; replacing an enriched credit with another artist causes a conflict. If direct `artist` elements exist, they are used and redundant simple `albumArtistCredits` blocks are removed; blocks containing identifiers, attributes or annotations remain. This cleans up redundant blocks added by earlier versions.

Conflicting albums, years or credits, uncataloged audio and missing cataloged tracks leave the NFO intact with an issue. Unsupported or malformed XML is neither converted nor overwritten. DTDs, entities and documents over 16 MiB are rejected; external resources are not accessed.

If the NFO contains a `<track>` list, target song titles update even when the audio title already matches. The general album title is handled separately; unselected song titles remain intact. Numbering must identify exactly one song and XML entry: missing or ambiguous matches cause conflicts. Leading zeros in position/disc are accepted. No absent track list is created, and its order, positions and durations are unchanged.

Reviews, labels, other images, identifiers, ratings, unknown fields, other track-list data, attributes/comments of retained elements and processing instructions are preserved. Writing may normalize XML representation; supported encoding, UTF-8 BOM and existing CRLF are retained. The original XML declaration, its content separation and final line breaks are preserved. A declaration joined to `<album>` by an earlier write is separated with a newline even without musical differences. Without data changes or header repair, content, timestamp and physical file remain unchanged.

Each NFO is published after its target audio files finish confirmed or unchanged. Audio failure leaves that folder's NFO pending. NFO failure preserves actual audio results and batch backups. Other albums can continue unless essential storage, catalog or logging fails. Cancellation retains already published work.

Output and JSON reports list NFOs separately as updated, unchanged, absent, pending, conflict or failed. Written-audio counts exclude NFOs. NFO errors offer the same report popup and allow retry. Publication followed by failure is explicitly identified as NFO replaced.

The [delivery plan](album-nfo-plan.md) details contracts and acceptance criteria.

## Supported formats and values

| Case | Behavior |
| --- | --- |
| FLAC | Modify Vorbis comments differing from the catalog; replace front artwork when a source is chosen and preserve other images, blocks and audio |
| MP3 with ID3v2.4 | Preserve v2.4 and ordered Unicode artist/genre lists |
| MP3 with ID3v2.3 | Preserve v2.3; block lists that would be joined on save. Do not convert to v2.4 |
| MP3 without ID3 | Create ID3v2.4 |
| ID3v2.2 or coexisting ID3v1 | Blocked; this delivery does not convert or discard legacy tags |
| Track/disc numbers and totals | Write saved numbers/totals. A total without a number reads back as a missing number |
| Full dates | Change year while preserving valid representable precision. Invalid/unrepresentable results become year-only; clearing year removes the date |
| Multiple USLT lyrics | Update the first lyrics version exposed by the reader and preserve others. Import may display another remaining version because it exposes only one lyrics text |
| Aliases and TXXX | Remove/update the modified field's family so an old alias cannot take precedence |
| Unrelated metadata | Verify comments, known/unknown frames, unselected images and trailing APEv2 tags; do not publish if preservation fails |

Numbers are serialized without inventing values; years use four digits in the range 1–9999. Writing does not split names on commas, semicolons or `/`. An empty saved field removes its tag. Empty lists remove their tag family. ID3v2.3 supports year, day or minute date precision; other precision reduces to year when the year changes. Progress identifies each incompatible file.

Audio hashes compare bytes after FLAC metadata blocks or between MP3 leading/trailing tags. Audio is not re-encoded, and verification does not rely only on duration or declared MD5. Tags are verified by reopening the modified copy before replacing the original.

## Files, permissions and space

Each file, including NFO, needs space for a complete backup and temporary copy. Processing is sequential: reserve space for all backups and the largest temporary file. Space is checked per volume before writing, with an additional 1 MiB margin. Symlinks/junctions are not followed; hard links and targets outside imported roots are not replaced. Missing/read-only originals are blocked, without preventing SQLite editing.

The imported root itself may be an alias, such as `/var` on macOS: normalize it for NFO operations and retain its stored spelling for catalog queries. Internal library links and target changes during the operation remain blocked.

Linux copies and checks mode, owner/group and extended attributes, including ACLs represented through those attributes. macOS uses libSystem `copyfile` to preserve permissions, ACLs and attributes, including resource forks, verified through native APIs. Non-resource-fork macOS attributes over 16 MiB are blocked to bound verification memory; resource forks are compared by streaming. Windows copies owner, group, DACL and named streams through native APIs; privileged SACL audit rules are not copied. Compressed/encrypted NTFS files are rejected. Metadata not exposed by the system, inode identity or creation time after replacement are not guaranteed. If required preservation fails, the original remains intact.

Copies and logs are synced to disk; POSIX also syncs directories where supported. This implementation does not provide directory sync on Windows. Publication uses same-volume `os.replace`. Final durability depends on filesystem and storage; checks cannot prevent every race with other music-editing programs.

## Results and cancellation

Each file may be confirmed, written with catalog pending, unchanged, excluded, conflicting, failed or pending. Output shows errors and backups; errors enable JSON export in the popup. Writing does not change saved musical values in the catalog.

**Close** during work requests cancellation, waits for a safe point and closes the dialog while preserving published files. The event loop remains responsive. Isolated failures allow other files to continue; catalog/log loss and essential storage failures stop pending work. There is no global transaction between files and SQLite, or automatic batch undo.

## Recovery

Before editing a copy, create a complete backup beside each original:

```text
<music folder>/.trackfolio-backups/<operation>/<id>-<name>.tfo-bak
```

Owned temporary files sit beside the original: `.trackfolio-<operation>-<id>.tmp`. These suffixes prevent music reimport. The NFO backup is `nfo-album.nfo.tfo-bak` inside the same operation directory; its temporary file is `.trackfolio-<operation>-album-nfo.tmp` beside the original.

After the entire batch, including NFOs, is written and confirmed without errors or cancellation, the complete `.trackfolio-backups` directory is removed from every folder where copies were created, including older UUID directories and backups. Cleanup waits for batch completion and logged confirmation; it is not per song. Unchanged results alone neither create copies nor delete old backups.

Failures, conflicts, catalog-pending states or cancellation retain batch copies. Cleanup failures are reported and paths of remaining copies retained; other folders may already have been removed.

The persistent log is in the user's data folder at `Trackfolio/tag-writes/<operation>/journal.json`. On Linux this is normally `~/.local/share/Trackfolio/tag-writes/`; `XDG_DATA_HOME` is respected and macOS/Windows use their `platformdirs` equivalent. Logs store paths, confirmed values, hashes and states without binary artwork. Version `3` adds cover sources, fingerprints and intents. Versions `1` (audio) and `2` (audio/NFO) remain supported. Review can confirm published artwork in SQLite without the original image source; it does not rewrite audio.

Logs remain as history. Backups retained after incomplete batches support manual recovery. The GUI has no pending-operation manager and does not resume writes at startup. The technical `ReviewTagWrites` use case remains available through Python contracts to inspect hashes, reconcile catalog observations and inspect NFO hashes without rewriting or restoring audio. Confirmation requires a valid catalog and snapshot; later edits remain conflicts.

To restore manually, close programs using the file, retain a copy of its current version and check the backup path in the report. Copy the `.tfo-bak` contents onto the original path with its original extension; backups are complete files, not a proprietary format. Retain backup and log until restoration is verified. SQLite keeps its corrections: reimporting replaces them with restored tags.

A partial temporary file not yet verified is retained for manual review after abrupt interruption; the report gives its path. Do not delete pending-operation backups/logs before resolving them. Closed logs remain as history.

Local and platform checks are recorded in [VALIDATION.md](../VALIDATION.md).

Platform references: [Windows permissions and inheritance](https://learn.microsoft.com/en-us/windows/win32/secauthz/security-information), [security descriptor representation](https://learn.microsoft.com/en-us/windows/win32/api/sddl/nf-sddl-convertsecuritydescriptortostringsecuritydescriptorw) and [stream enumeration](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-findfirststreamw). For macOS: [copyfile and metadata](https://developer.apple.com/library/archive/documentation/System/Conceptual/ManPages_iPhoneOS/man3/copyfile.3.html) and [ACL](https://developer.apple.com/library/archive/documentation/System/Conceptual/ManPages_iPhoneOS/man3/acl_get_file.3.html).
