"""Plan, publish and inspect optional album sidecars through desktop-free ports."""

from __future__ import annotations

import errno
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Protocol

from trackfolio.application.tag_write_errors import (
    TagJournalError,
    TagPublishedError,
    TagWriteCancelled,
    TagWriteConflict,
)
from trackfolio.domain.tag_write import (
    AlbumNfoItem,
    AlbumNfoResult,
    AlbumNfoSong,
    AlbumNfoTrack,
    AlbumNfoValues,
    TagWritePreview,
    TagWriteProgress,
    TagWriteResult,
)

if TYPE_CHECKING:
    from trackfolio.application.write_tags import TagCatalog, TagFiles, TagJournal


class AlbumNfoCodec(Protocol):
    def plan(self, path: Path, values: AlbumNfoValues) -> bool: ...

    def write_verified(self, backup: Path, temporary: Path, values: AlbumNfoValues) -> None: ...


def album_values(
    tracks: tuple[AlbumNfoTrack, ...], selected_ids: tuple[int, ...] = ()
) -> AlbumNfoValues:
    if not tracks:
        raise TagWriteConflict("The folder contains no cataloged tracks.")
    if len({track.album for track in tracks}) != 1 or len({track.year for track in tracks}) != 1:
        raise TagWriteConflict("The folder's tracks have different albums or years.")
    credits = {track.album_artists for track in tracks}
    if len(credits) != 1:
        raise TagWriteConflict("The folder's tracks have conflicting album credits.")
    artists: tuple[str, ...] | None = tracks[0].album_artists
    if not artists:
        artists = tracks[0].artists if len({track.artists for track in tracks}) == 1 else None
    genres = tuple(dict.fromkeys(genre for track in tracks for genre in track.genres))
    songs = tuple(
        AlbumNfoSong(
            track.file_id,
            track.title,
            track.track_number,
            track.disc_number,
            track.file_id in selected_ids,
        )
        for track in tracks
    )
    return AlbumNfoValues(tracks[0].album, tracks[0].year, genres, artists, songs)


class AlbumNfoWrites:
    def __init__(self, catalog: TagCatalog, files: TagFiles, codec: AlbumNfoCodec) -> None:
        self.catalog, self.files, self.codec = catalog, files, codec

    def prepare(
        self,
        preview: TagWritePreview,
        cancelled: Callable[[], bool],
        progress: Callable[[TagWriteProgress], None],
    ) -> tuple[AlbumNfoItem, ...]:
        groups: dict[Path, list[int]] = {}
        roots: dict[Path, set[Path]] = {}
        for audio in preview.items:
            if audio.snapshot is not None:
                snapshot = audio.snapshot
                root = snapshot.library_root
                # Root aliases are allowed by audio writes (e.g. /var on macOS).
                # Keep the imported spelling for catalogue queries, but use the
                # physical root for all sidecar filesystem operations.
                path = (root.resolve() / snapshot.relative_path).parent / "album.nfo"
                groups.setdefault(path, []).append(audio.file_id)
                roots.setdefault(path, set()).add(root)
        items = []
        for index, (path, file_ids) in enumerate(sorted(groups.items())):
            if cancelled():
                raise TagWriteCancelled("NFO preparation cancelled.")
            item = AlbumNfoItem(path, sorted(roots[path])[0], tuple(file_ids))
            progress(TagWriteProgress("nfo_reading", index, len(groups), path))
            try:
                if len(roots[path]) != 1:
                    raise TagWriteConflict("The NFO belongs to overlapping libraries.")
                # Validate the folder even when the optional file is absent.
                members = self.files.folder_members(item.library_root, path.parent)
                item = replace(item, members=members)
                if not path.exists() and not path.is_symlink():
                    items.append(replace(item, state="absent"))
                    continue
                resolved = self.files.resolve_target(item.library_root, path)
                if resolved != path:
                    raise TagWriteConflict("The NFO path changed during resolution.")
                fingerprint = self.files.fingerprint(path, cancelled)
                tracks = self.catalog.album_tracks(
                    preview.request.database_path, item.library_root, path.parent
                )
                item = replace(item, tracks=tracks, fingerprint=fingerprint)
                catalog_members = tuple(sorted(PurePosixPath(t.relative_path).name for t in tracks))
                if catalog_members != members:
                    raise TagWriteConflict(
                        "The folder contains uncataloged audio or missing tracks."
                    )
                values = album_values(tracks, item.file_ids)
                covers = {
                    audio.tags.cover.path.name
                    for audio in preview.items
                    if audio.file_id in item.file_ids
                    and audio.tags is not None
                    and audio.tags.cover is not None
                }
                if len(covers) > 1:
                    raise TagWriteConflict("Different covers have been selected for the NFO.")
                if covers:
                    values = replace(values, thumb=next(iter(covers)))
                item = replace(item, values=values)
                changed = self.codec.plan(path, values)
                self.check(preview, item, cancelled)
                items.append(replace(item, state="ready" if changed else "unchanged"))
            except TagWriteCancelled:
                raise
            except Exception as exc:
                items.append(
                    replace(
                        item,
                        state="conflict" if isinstance(exc, TagWriteConflict) else "blocked",
                        message=str(exc),
                    )
                )
        return tuple(items)

    def check(
        self, preview: TagWritePreview, item: AlbumNfoItem, cancelled: Callable[[], bool]
    ) -> None:
        try:
            identity = self.files.identity(preview.request.database_path)
        except OSError as exc:
            raise TagJournalError(f"The catalog is no longer available: {exc}") from exc
        if identity != preview.catalog_identity:
            raise TagJournalError("The catalog was replaced during the NFO write.")
        if self.files.folder_members(item.library_root, item.path.parent) != item.members:
            raise TagWriteConflict("The folder contents changed after NFO preparation.")
        if item.state == "absent":
            if item.path.exists() or item.path.is_symlink():
                raise TagWriteConflict("The NFO appeared after preparation; try again.")
            return
        try:
            self.files.resolve_target(item.library_root, item.path)
            current = self.files.fingerprint(item.path, cancelled)
        except FileNotFoundError as exc:
            raise TagWriteConflict("The NFO disappeared after write preparation.") from exc
        if current != item.fingerprint:
            raise TagWriteConflict("The NFO changed after write preparation.")
        tracks = self.catalog.album_tracks(
            preview.request.database_path, item.library_root, item.path.parent
        )
        if tracks != item.tracks:
            raise TagWriteConflict("The album data changed after NFO preparation.")

    def unchanged_results(
        self, preview: TagWritePreview, cancelled: Callable[[], bool]
    ) -> tuple[AlbumNfoResult, ...]:
        """Revalidate an operation with no writes, without creating a journal or writer."""
        results = []
        for item in preview.nfo_items:
            try:
                if cancelled():
                    raise TagWriteCancelled("NFO check cancelled.")
                self.check(preview, item, cancelled)
                assert item.state in ("absent", "unchanged")
                results.append(AlbumNfoResult(item.path, item.state))
            except Exception as exc:
                results.append(
                    AlbumNfoResult(
                        item.path,
                        "pending"
                        if isinstance(exc, TagWriteCancelled)
                        else "conflict"
                        if isinstance(exc, TagWriteConflict)
                        else "failed",
                        str(exc),
                    )
                )
        return tuple(results)

    def execute(
        self,
        preview: TagWritePreview,
        audio_results: tuple[TagWriteResult, ...],
        journal: TagJournal,
        cancelled: Callable[[], bool],
        progress: Callable[[TagWriteProgress], None],
        fatal: str | None,
    ) -> tuple[tuple[AlbumNfoResult, ...], str | None]:
        audio = {result.file_id: result.state for result in audio_results}
        results: list[AlbumNfoResult] = []
        for index, item in enumerate(preview.nfo_items):
            if item.state in ("blocked", "conflict"):
                results.append(
                    AlbumNfoResult(
                        item.path,
                        "conflict" if item.state == "conflict" else "failed",
                        item.message,
                    )
                )
                continue
            if (
                cancelled()
                or fatal
                or any(
                    audio.get(file_id) not in ("confirmed", "unchanged")
                    for file_id in item.file_ids
                )
            ):
                results.append(
                    AlbumNfoResult(
                        item.path,
                        "pending",
                        "NFO pending: the audio group did not finish successfully.",
                    )
                )
                continue
            backup, temporary = journal.nfo_paths(item)
            backed_up = published = False
            progress(TagWriteProgress("nfo_writing", index, len(preview.nfo_items), item.path))
            try:
                self.check(preview, item, cancelled)
                if item.state in ("absent", "unchanged"):
                    journal.record_nfo(item, item.state)
                    results.append(AlbumNfoResult(item.path, item.state))
                    continue
                assert item.values is not None
                self.files.backup(item, backup, cancelled)
                backed_up = True
                journal.record_nfo(item, "backup_verified")
                self.files.temporary(backup, temporary, cancelled)
                self.codec.write_verified(backup, temporary, item.values)
                after = self.files.fingerprint(temporary, cancelled)
                journal.record_nfo(
                    item,
                    "temporary_verified",
                    after_hash=after.sha256,
                    temporary_identity=(after.device, after.inode),
                )
                if cancelled():
                    raise TagWriteCancelled("Cancelled before publishing the NFO.")
                self.check(preview, item, cancelled)
                journal.record_nfo(item, "publishing", after_hash=after.sha256)
                self.files.publish(item, temporary)
                published = True
                journal.record_nfo(item, "written", after_hash=after.sha256)
                if self.files.fingerprint(item.path, lambda: False).sha256 != after.sha256:
                    raise TagWriteConflict("The NFO changed after publication.")
                journal.record_nfo(item, "updated", after_hash=after.sha256)
                results.append(
                    AlbumNfoResult(item.path, "updated", backup_path=backup, published=True)
                )
            except Exception as exc:
                published = published or isinstance(exc, TagPublishedError)
                result = AlbumNfoResult(
                    item.path,
                    "pending"
                    if isinstance(exc, TagWriteCancelled)
                    else "conflict"
                    if isinstance(exc, TagWriteConflict)
                    else "failed",
                    ("NFO replaced; review required. " if published else "") + str(exc),
                    backup if backed_up else None,
                    published,
                )
                results.append(result)
                try:
                    journal.record_nfo(
                        item, result.state, error=result.message, published=published
                    )
                except Exception as record_error:
                    fatal = f"Could not record the NFO result: {record_error}"
                if isinstance(exc, TagJournalError) or (
                    isinstance(exc, OSError)
                    and exc.errno in (errno.ENOSPC, errno.EDQUOT, errno.EIO)
                ):
                    fatal = str(exc)
            finally:
                try:
                    self.files.discard_temporary(temporary)
                except OSError as exc:
                    fatal = fatal or f"Could not clean up the temporary NFO: {exc}"
        return tuple(results), fatal


def review_nfos(
    preview: TagWritePreview,
    journal: TagJournal,
    files: TagFiles,
    cancelled: Callable[[], bool],
    reconcile: bool,
) -> tuple[AlbumNfoResult, ...]:
    results = []
    for item in preview.nfo_items:
        backup, temporary = journal.nfo_paths(item)
        available = backup if backup.is_file() else None
        published = False
        try:
            if cancelled():
                raise TagWriteCancelled("NFO review cancelled.")
            state = journal.nfo_state(item)
            if item.state == "absent" and not item.path.exists() and not item.path.is_symlink():
                results.append(AlbumNfoResult(item.path, "absent"))
                continue
            files.resolve_target(item.library_root, item.path)
            current = files.fingerprint(item.path, cancelled)
            if state.after_hash and current.sha256 == state.after_hash:
                published = True
                if reconcile:
                    journal.record_nfo(item, "updated", published=True)
                results.append(
                    AlbumNfoResult(
                        item.path,
                        "updated",
                        "NFO publication verified by hash.",
                        available,
                        True,
                    )
                )
            elif item.fingerprint and current.sha256 == item.fingerprint.sha256:
                if reconcile:
                    files.discard_recovery_temporary(temporary, state)
                results.append(
                    AlbumNfoResult(
                        item.path,
                        "unchanged" if state.state == "unchanged" else "pending",
                        "Original NFO intact. Writing is not resumed."
                        + (f" Temporal conservado: {temporary}" if temporary.exists() else ""),
                        available,
                    )
                )
            else:
                raise TagWriteConflict("The NFO does not match any recorded version.")
        except Exception as exc:
            results.append(
                AlbumNfoResult(
                    item.path,
                    "pending" if isinstance(exc, TagWriteCancelled) else "conflict",
                    str(exc),
                    available,
                    published,
                )
            )
    return tuple(results)
