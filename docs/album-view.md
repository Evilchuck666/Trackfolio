# Album view

The **Albums** tab displays catalog editions in a searchable list. Selecting one shows its SQLite artwork, album artists, year, genres, folder, track/disc counts and available duration. Tracks are sorted by disc and number; double-click opens the song in **Songs**. Browsing and editing work even when music is disconnected.

## Grouping

The view uses the edition's library and folder, title, year, date, album artists and disc total. Same-named albums in other folders or libraries, and conflicting metadata, remain separate. Browsing does not modify or merge original records.

Subdirectories named `CD 1`, `CD2`, `Disc 01`, `Disk 2` or `Disco 2` belong to their parent folder only when the number matches the track's saved disc number. Other directories remain separate. Arbitrary folders are not combined merely because they share a title.

Track artists do not determine grouping: a compilation may contain different performers. Missing album artists are displayed as missing, without inventing credits from performers.

## Edit an album

1. Click **Edit album** or press `Ctrl+E` from the tab.
2. Check fields to apply to all tracks: album, year, album artists or genres. Unchecked fields are preserved; a checked empty field is cleared.
3. Add full names and reorder them using the list controls. Names are not split on commas, slashes or semicolons. If track genres differ, the editor indicates **Mixed values** and requires checking the field before replacement.
4. Click **Save album** or press `Ctrl+S`. Saving uses one transaction for the album tracks loaded when editing began. Concurrent changes cause a conflict and preserve the draft without saving part of the album.

Saving preserves individual song artists, titles, numbering and lyrics. Editions in other folders remain intact. The view refreshes after saving and retains the selected album even if its name changes.

Switching albums or tabs, refreshing, opening another catalog, importing, writing tags or closing the window resolves pending changes through **Save / Discard / Cancel**. Shortcuts act on the visible editor.

## Write to music

**Write album tags…** prepares the existing dialog for all album tracks, including multiple discs. Clicking **Write tags** publishes saved catalog data with the same checks, temporary files, backups and reports as the song view. Album artists are written as `ALBUMARTIST` in FLAC or `TPE2` in MP3; track artists still use `ARTIST` / `TPE1`.

Artwork is chosen per physical folder under the [artwork rules](tag-writing.md#embedding-artwork). Existing `album.nfo` files in song folders are updated under the [NFO rules](tag-writing.md#optional-albumnfo-updates). Grouping discs in this view does not extend the NFO search to parent folders. **Save album** alone does not modify music files.
