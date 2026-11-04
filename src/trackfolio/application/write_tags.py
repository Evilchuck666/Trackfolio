"""Preview and coordinate recoverable audio writes through desktop-free contracts."""

from __future__ import annotations

import errno
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import Protocol, cast
from uuid import uuid4

from trackfolio.application.album_nfo import AlbumNfoCodec, AlbumNfoWrites, review_nfos
from trackfolio.application.cover_writes import CoverSources, discover_covers, resolve_covers
from trackfolio.application.edit_catalog import validate_edit_patch
from trackfolio.application.tag_write_errors import (
    TagJournalError as TagJournalError,
)
from trackfolio.application.tag_write_errors import (
    TagPublishedError as TagPublishedError,
)
from trackfolio.application.tag_write_errors import (
    TagWriteCancelled as TagWriteCancelled,
)
from trackfolio.application.tag_write_errors import (
    TagWriteConflict as TagWriteConflict,
)
from trackfolio.application.tag_write_errors import (
    TagWriteError as TagWriteError,
)
from trackfolio.domain.catalog_edit import EDIT_FIELDS, FieldChange, TrackEditPatch
from trackfolio.domain.metadata import TrackMetadata
from trackfolio.domain.tag_write import (
    AlbumNfoItem,
    AlbumNfoResult,
    AlbumNfoTrack,
    CoverChoice,
    CoverDiscovery,
    FileFingerprint,
    PendingTagOperation,
    PlannedTags,
    TagCatalogSnapshot,
    TagItemState,
    TagRecoveryState,
    TagResultState,
    TagWriteItem,
    TagWritePreview,
    TagWriteProgress,
    TagWriteReport,
    TagWriteRequest,
    TagWriteResult,
)


class TagCatalog(Protocol):
    def album_tracks(self, path: Path, root: Path, folder: Path) -> tuple[AlbumNfoTrack, ...]: ...

    def snapshot(self, path: Path, file_id: int) -> TagCatalogSnapshot: ...

    def prepare(self, path: Path) -> None: ...

    def check(self, path: Path, snapshot: TagCatalogSnapshot) -> None: ...

    def confirm(
        self,
        path: Path,
        snapshot: TagCatalogSnapshot,
        observed: TrackMetadata,
        date_written: bool,
        cover_written: bool = False,
    ) -> None: ...


class TagCodec(Protocol):
    def observed(self, path: Path) -> TrackMetadata: ...
    def plan(
        self, path: Path, snapshot: TagCatalogSnapshot, request: TagWriteRequest
    ) -> PlannedTags: ...

    def write_verified(self, backup: Path, temporary: Path, plan: PlannedTags) -> TrackMetadata: ...


class TagJournal(Protocol):
    path: Path

    @property
    def preview(self) -> TagWritePreview: ...

    def state(self, file_id: int) -> TagRecoveryState: ...

    def nfo_state(self, item: AlbumNfoItem) -> TagRecoveryState: ...

    def nfo_paths(self, item: AlbumNfoItem) -> tuple[Path, Path]: ...

    def record_nfo(self, item: AlbumNfoItem, state: str, **details: object) -> None: ...

    def paths(self, item: TagWriteItem) -> tuple[Path, Path]: ...

    def record(self, item: TagWriteItem, state: str, **details: object) -> None: ...

    def finish(self, report: TagWriteReport) -> None: ...


class WriteTarget(Protocol):
    @property
    def path(self) -> Path: ...

    @property
    def fingerprint(self) -> FileFingerprint | None: ...


class TagFiles(Protocol):
    def identity(self, path: Path) -> tuple[int, int]: ...

    def resolve(self, snapshot: TagCatalogSnapshot) -> Path: ...

    def resolve_target(self, root: Path, path: Path) -> Path: ...

    def folder_members(self, root: Path, folder: Path) -> tuple[str, ...]: ...

    def reserve(self, items: tuple[WriteTarget, ...]) -> None: ...

    def fingerprint(self, path: Path, cancelled: Callable[[], bool]) -> FileFingerprint: ...

    def check(self, item: TagWriteItem, cancelled: Callable[[], bool]) -> None: ...

    def journal(self, preview: TagWritePreview) -> TagJournal: ...

    def backup(self, item: WriteTarget, path: Path, cancelled: Callable[[], bool]) -> None: ...

    def temporary(self, backup: Path, temporary: Path, cancelled: Callable[[], bool]) -> None: ...

    def publish(self, item: WriteTarget, temporary: Path) -> None: ...

    def discard_temporary(self, path: Path) -> None: ...

    def discard_backups(self, directory: Path) -> None: ...

    def discard_recovery_temporary(self, path: Path, state: TagRecoveryState) -> None: ...

    def pending(self) -> tuple[PendingTagOperation, ...]: ...

    def load_journal(self, path: Path) -> TagJournal: ...


def _never_cancel() -> bool:
    return False


def _ignore_progress(progress: TagWriteProgress) -> None:
    pass


class PreviewTagWrites:
    def __init__(self, catalog: TagCatalog, codec: TagCodec, files: TagFiles) -> None:
        self.catalog, self.codec, self.files = catalog, codec, files

    def execute(
        self,
        request: TagWriteRequest,
        *,
        is_cancelled: Callable[[], bool] = _never_cancel,
        on_progress: Callable[[TagWriteProgress], None] = _ignore_progress,
    ) -> TagWritePreview:
        if not request.file_ids or len(set(request.file_ids)) != len(request.file_ids):
            raise TagWriteError("Select distinct songs to write tags.")
        if (
            not request.fields
            or len(set(request.fields)) != len(request.fields)
            or any(field not in EDIT_FIELDS for field in request.fields)
        ):
            raise TagWriteError("Select the fields you want to write.")
        identity = self.files.identity(request.database_path)
        items: list[TagWriteItem] = []
        physical: dict[tuple[int, int], int] = {}
        for index, file_id in enumerate(request.file_ids):
            if is_cancelled():
                raise TagWriteCancelled("Preview cancelled.")
            path = Path("")
            snapshot = None
            fingerprint = None
            tags = None
            on_progress(TagWriteProgress("preview", index, len(request.file_ids)))
            try:
                snapshot = self.catalog.snapshot(request.database_path, file_id)
                path = snapshot.library_root / snapshot.relative_path
                path = self.files.resolve(snapshot)
                on_progress(TagWriteProgress("reading", index, len(request.file_ids), path))
                fingerprint = self.files.fingerprint(path, is_cancelled)
                key = fingerprint.device, fingerprint.inode
                tags = self.codec.plan(path, snapshot, request)
                if self.files.fingerprint(path, is_cancelled) != fingerprint:
                    raise TagWriteConflict("The file changed while the preview was being prepared.")
                if key in physical:
                    previous = physical[key]
                    items[previous] = replace(
                        items[previous],
                        state="conflict",
                        message="Another record points to the same file. Check its paths.",
                    )
                    raise TagWriteConflict("Two records point to the same physical file.")
                physical[key] = len(items)
                validate_edit_patch(
                    tags.before,
                    TrackEditPatch(
                        tuple(FieldChange(diff.field, diff.after) for diff in tags.differences)
                    ),
                )
                state = (
                    "blocked"
                    if tags.error
                    else "ready"
                    if (tags.differences or tags.cover_changed or tags.cover_catalog_changed)
                    else "unchanged"
                )
                item = TagWriteItem(
                    file_id,
                    path,
                    snapshot,
                    fingerprint,
                    tags,
                    cast(TagItemState, state),
                    tags.error or "",
                )
            except TagWriteCancelled:
                raise
            except Exception as exc:
                item = TagWriteItem(
                    file_id,
                    path,
                    snapshot,
                    fingerprint,
                    tags,
                    "conflict" if isinstance(exc, TagWriteConflict) else "blocked",
                    str(exc),
                )
            items.append(item)
        if self.files.identity(request.database_path) != identity:
            raise TagWriteConflict("The catalog was replaced during preview.")
        return TagWritePreview(uuid4().hex, request, identity, tuple(items))


def _cover_results(report: TagWriteReport, preview: TagWritePreview) -> TagWriteReport:
    plans = {item.file_id: item.tags for item in preview.items}
    results = []
    for result in report.results:
        plan = plans.get(result.file_id)
        if plan is not None:
            action = (
                plan.cover_action
                if result.state in ("confirmed", "catalog_pending", "unchanged")
                else "preserved"
            )
            result = replace(
                result, cover_action=action, cover_path=plan.cover.path if plan.cover else None
            )
        results.append(result)
    return replace(report, results=tuple(results))


class WriteTagWrites:
    def __init__(
        self,
        catalog: TagCatalog,
        codec: TagCodec,
        files: TagFiles,
        nfo_writer: AlbumNfoWrites | None = None,
        cover_sources: CoverSources | None = None,
    ) -> None:
        self.catalog, self.codec, self.files = catalog, codec, files
        self.nfo_writer = nfo_writer
        self.cover_sources = cover_sources

    def _check_cover(
        self, preview: TagWritePreview, item: TagWriteItem, cancelled: Callable[[], bool]
    ) -> None:
        if self.cover_sources is None or item.file_id in preview.request.cover_skipped_ids:
            return
        for folder in preview.cover_folders:
            if item.file_id in folder.file_ids:
                if (
                    item.snapshot is None
                    or item.snapshot.library_root.resolve() != folder.library_root
                    or item.path.parent != folder.path
                ):
                    raise TagWriteConflict("The library changed during cover selection.")
                self.cover_sources.check(folder, item.tags.cover if item.tags else None, cancelled)
                return

    def _check_catalog(self, preview: TagWritePreview) -> None:
        try:
            identity = self.files.identity(preview.request.database_path)
        except OSError as exc:
            raise TagJournalError(f"The catalog is no longer available: {exc}") from exc
        if identity != preview.catalog_identity:
            raise TagJournalError("The catalog was replaced during writing.")

    def execute(
        self,
        preview: TagWritePreview,
        selected_ids: tuple[int, ...],
        *,
        is_cancelled: Callable[[], bool] = _never_cancel,
        on_progress: Callable[[TagWriteProgress], None] = _ignore_progress,
    ) -> TagWriteReport:
        eligible = {item.file_id for item in preview.items if item.state == "ready"}
        if preview.nfo_items and self.nfo_writer is None:
            raise TagWriteError("The operation requires a configured NFO writer.")
        if (
            (not selected_ids and not preview.nfo_items)
            or len(set(selected_ids)) != len(selected_ids)
            or not set(selected_ids) <= eligible
        ):
            raise TagWriteError("Select writable files from the preview.")
        if self.files.identity(preview.request.database_path) != preview.catalog_identity:
            raise TagWriteConflict("The catalog was replaced. Prepare another preview.")
        if is_cancelled():
            return TagWriteReport(
                preview.operation_id,
                tuple(TagWriteResult(i.file_id, i.path, "pending") for i in preview.items),
                cancelled=True,
                nfo_results=tuple(
                    AlbumNfoResult(item.path, "pending") for item in preview.nfo_items
                ),
            )
        self.catalog.prepare(preview.request.database_path)
        journal = self.files.journal(preview)
        results: list[TagWriteResult] = []
        fatal = None
        try:
            self.files.reserve(
                tuple(
                    [
                        item
                        for item in preview.items
                        if item.file_id in selected_ids
                        and item.tags is not None
                        and (item.tags.differences or item.tags.cover_changed)
                    ]
                    + [item for item in preview.nfo_items if item.state == "ready"]
                )
            )
        except OSError as exc:
            fatal = str(exc)
        for index, item in enumerate(preview.items):
            if item.file_id not in selected_ids:
                results.append(
                    TagWriteResult(
                        item.file_id,
                        item.path,
                        "unchanged" if item.state == "unchanged" else "excluded",
                        item.message,
                    )
                )
                continue
            if is_cancelled() or fatal:
                results.append(TagWriteResult(item.file_id, item.path, "pending"))
                continue
            assert item.snapshot is not None and item.tags is not None
            backup, temporary = journal.paths(item)
            published = False
            backed_up = False
            on_progress(TagWriteProgress("checking", index, len(preview.items), item.path))
            try:
                self._check_catalog(preview)
                self.catalog.check(preview.request.database_path, item.snapshot)
                self.files.check(item, is_cancelled)
                self._check_cover(preview, item, is_cancelled)
                if (
                    item.tags.cover is not None
                    and not item.tags.cover_changed
                    and not item.tags.differences
                ):
                    assert item.fingerprint is not None
                    journal.record(item, "confirming_cover", after_hash=item.fingerprint.sha256)
                    self.catalog.confirm(
                        preview.request.database_path,
                        item.snapshot,
                        self.codec.observed(item.path),
                        False,
                        cover_written=True,
                    )
                    journal.record(item, "confirmed")
                    results.append(
                        TagWriteResult(
                            item.file_id,
                            item.path,
                            "unchanged",
                            "Cover matches; catalog thumbnail updated.",
                            catalog_updated=True,
                        )
                    )
                    continue
                on_progress(TagWriteProgress("backup", index, len(preview.items), item.path))
                self.files.backup(item, backup, is_cancelled)
                backed_up = True
                journal.record(item, "backup_verified")
                self.files.temporary(backup, temporary, is_cancelled)
                on_progress(TagWriteProgress("writing", index, len(preview.items), item.path))
                observed = self.codec.write_verified(backup, temporary, item.tags)
                after = self.files.fingerprint(temporary, is_cancelled)
                journal.record(
                    item,
                    "temporary_verified",
                    after_hash=after.sha256,
                    temporary_identity=(after.device, after.inode),
                )
                if is_cancelled():
                    raise TagWriteCancelled("Cancelled before publishing the file.")
                self._check_catalog(preview)
                self.catalog.check(preview.request.database_path, item.snapshot)
                self.files.check(item, is_cancelled)
                self._check_cover(preview, item, is_cancelled)
                journal.record(item, "publishing", after_hash=after.sha256)
                # Once published, always record the outcome even if cancellation arrives.
                self.files.publish(item, temporary)
                published = True
                journal.record(item, "written", after_hash=after.sha256)
                if self.files.fingerprint(item.path, _never_cancel).sha256 != after.sha256:
                    raise TagWriteConflict("The file changed after publication.")
                self._check_catalog(preview)
                date_written = any(diff.field == "album_year" for diff in item.tags.differences)
                if item.tags.cover is not None:
                    self.catalog.confirm(
                        preview.request.database_path,
                        item.snapshot,
                        observed,
                        date_written,
                        cover_written=True,
                    )
                else:
                    self.catalog.confirm(
                        preview.request.database_path, item.snapshot, observed, date_written
                    )
                journal.record(item, "confirmed", after_hash=after.sha256)
                results.append(
                    TagWriteResult(item.file_id, item.path, "confirmed", backup_path=backup)
                )
            except Exception as exc:
                published = published or isinstance(exc, TagPublishedError)
                state = (
                    "catalog_pending"
                    if published
                    else "pending"
                    if isinstance(exc, TagWriteCancelled)
                    else "conflict"
                    if isinstance(exc, TagWriteConflict)
                    else "failed"
                )
                results.append(
                    TagWriteResult(
                        item.file_id,
                        item.path,
                        cast(TagResultState, state),
                        str(exc),
                        backup if backed_up else None,
                    )
                )
                try:
                    journal.record(item, state, error=str(exc))
                except Exception as record_error:
                    fatal = f"Could not record the result: {record_error}"
                if isinstance(exc, TagJournalError):
                    fatal = str(exc)
                if isinstance(exc, OSError) and exc.errno in (
                    errno.ENOSPC,
                    errno.EDQUOT,
                    errno.EIO,
                ):
                    fatal = str(exc)
            finally:
                try:
                    self.files.discard_temporary(temporary)
                except OSError as exc:
                    # The journal retains its reserved path for assisted cleanup.
                    fatal = fatal or f"Could not clean up the temporary file: {exc}"
        nfo_results: tuple[AlbumNfoResult, ...] = ()
        if self.nfo_writer is not None:
            nfo_results, fatal = self.nfo_writer.execute(
                preview, tuple(results), journal, is_cancelled, on_progress, fatal
            )
        report = TagWriteReport(
            preview.operation_id, tuple(results), journal.path, is_cancelled(), fatal, nfo_results
        )
        report = _cover_results(report, preview)
        try:
            journal.finish(report)
        except Exception as exc:
            report = replace(report, fatal_error=f"Could not close the report: {exc}")
        if is_cancelled():
            report = replace(report, cancelled=True)
        if (
            not report.cancelled
            and not report.fatal_error
            and all(item.state in ("confirmed", "unchanged") for item in report.results)
            and all(item.state in ("updated", "unchanged", "absent") for item in report.nfo_results)
        ):
            directories = sorted(
                {item.backup_path.parent.parent for item in report.results if item.backup_path}
                | {nfo.backup_path.parent.parent for nfo in report.nfo_results if nfo.backup_path}
            )
            for directory in directories:
                try:
                    self.files.discard_backups(directory)
                except Exception as exc:
                    report = replace(report, fatal_error=f"Could not remove backups: {exc}")
                    break
            remaining: list[TagWriteResult] = []
            for result in report.results:
                try:
                    removed = result.backup_path is not None and not result.backup_path.is_file()
                except OSError:
                    removed = False  # Keep its location if access cannot be checked.
                remaining.append(replace(result, backup_path=None) if removed else result)
            report = replace(report, results=tuple(remaining))
            remaining_nfos = []
            for nfo in report.nfo_results:
                try:
                    removed = nfo.backup_path is not None and not nfo.backup_path.is_file()
                except OSError:
                    removed = False
                remaining_nfos.append(replace(nfo, backup_path=None) if removed else nfo)
            report = replace(report, nfo_results=tuple(remaining_nfos))
            try:
                journal.finish(report)
            except Exception as exc:
                report = replace(report, fatal_error=f"Could not close the report: {exc}")
        on_progress(TagWriteProgress("finished", len(preview.items), len(preview.items)))
        return report


class ReviewTagWrites:
    """Inspect a journal; explicit confirmation can reconcile SQLite, never audio."""

    def __init__(self, catalog: TagCatalog, codec: TagCodec, files: TagFiles) -> None:
        self.catalog, self.codec, self.files = catalog, codec, files

    def execute(
        self,
        path: Path,
        *,
        reconcile: bool = False,
        is_cancelled: Callable[[], bool] = _never_cancel,
    ) -> TagWriteReport:
        journal = self.files.load_journal(path)
        preview = journal.preview
        results = []
        for item in preview.items:
            if is_cancelled():
                results.append(
                    TagWriteResult(item.file_id, item.path, "pending", "Review cancelled.")
                )
                continue
            state = journal.state(item.file_id)
            backup, temporary = journal.paths(item)
            available_backup = backup if backup.is_file() else None
            if state.state in ("confirmed", "unchanged", "excluded"):
                results.append(
                    TagWriteResult(
                        item.file_id,
                        item.path,
                        cast(TagResultState, state.state),
                        "Resultado registrado previamente.",
                        available_backup if state.state == "confirmed" else None,
                    )
                )
                continue
            try:
                current = self.files.fingerprint(item.path, is_cancelled)
                if state.after_hash and current.sha256 == state.after_hash:
                    if reconcile:
                        if (
                            self.files.identity(preview.request.database_path)
                            != preview.catalog_identity
                        ):
                            raise TagWriteConflict(
                                "The catalog was replaced; this record will not be confirmed."
                            )
                        if item.snapshot is None or item.tags is None:
                            raise TagWriteError("The record snapshot is incomplete.")
                        observed = self.codec.observed(item.path)
                        date_written = any(
                            diff.field == "album_year" for diff in item.tags.differences
                        )
                        if item.tags.cover is not None:
                            self.catalog.confirm(
                                preview.request.database_path,
                                item.snapshot,
                                observed,
                                date_written,
                                cover_written=True,
                            )
                        else:
                            self.catalog.confirm(
                                preview.request.database_path, item.snapshot, observed, date_written
                            )
                        journal.record(item, "confirmed")
                        results.append(
                            TagWriteResult(
                                item.file_id, item.path, "confirmed", backup_path=available_backup
                            )
                        )
                    else:
                        results.append(
                            TagWriteResult(
                                item.file_id,
                                item.path,
                                "catalog_pending",
                                "The file matches the verified result. "
                                "Its confirmation can be reviewed.",
                                available_backup,
                            )
                        )
                elif item.fingerprint and current.sha256 == item.fingerprint.sha256:
                    if reconcile:
                        self.files.discard_recovery_temporary(temporary, state)
                    results.append(
                        TagWriteResult(
                            item.file_id,
                            item.path,
                            "pending",
                            "Original intact. Writing has not resumed. "
                            "Prepare another preview if you want to write it."
                            + (
                                f" Temporary file retained for manual review: {temporary}"
                                if temporary.exists()
                                else ""
                            ),
                            available_backup,
                        )
                    )
                else:
                    raise TagWriteConflict(
                        "The file does not match any recorded version. Check its backup."
                    )
            except Exception as exc:
                results.append(
                    TagWriteResult(
                        item.file_id,
                        item.path,
                        "pending" if isinstance(exc, TagWriteCancelled) else "conflict",
                        str(exc),
                        available_backup,
                    )
                )
        nfo_results = review_nfos(preview, journal, self.files, is_cancelled, reconcile)
        report = _cover_results(
            TagWriteReport(
                preview.operation_id, tuple(results), path, is_cancelled(), nfo_results=nfo_results
            ),
            preview,
        )
        if reconcile and not report.cancelled:
            # Conflicts must remain discoverable instead of becoming silently closed.
            if any(item.state == "conflict" for item in results):
                report = replace(report, fatal_error="There are conflicts requiring manual review.")
            journal.finish(report)
        return report


class TagWriteService:
    """Composition facade shared by GUI, diagnostics and future interfaces."""

    def __init__(
        self,
        catalog: TagCatalog,
        codec: TagCodec,
        files: TagFiles,
        nfo_codec: AlbumNfoCodec | None = None,
        cover_sources: CoverSources | None = None,
    ) -> None:
        self.previewer = PreviewTagWrites(catalog, codec, files)
        self.nfo_writer = (
            AlbumNfoWrites(catalog, files, nfo_codec) if nfo_codec is not None else None
        )
        self.cover_sources = cover_sources
        self.catalog = catalog
        self.writer = WriteTagWrites(catalog, codec, files, self.nfo_writer, cover_sources)
        self.reviewer = ReviewTagWrites(catalog, codec, files)
        self.files = files

    def discover_covers(
        self,
        database: Path,
        file_ids: tuple[int, ...],
        *,
        is_cancelled: Callable[[], bool] = _never_cancel,
        on_progress: Callable[[TagWriteProgress], None] = _ignore_progress,
    ) -> CoverDiscovery:
        if self.cover_sources is None:
            return CoverDiscovery(database, file_ids, self.files.identity(database), (), ())
        return discover_covers(
            self.catalog,
            self.files,
            self.cover_sources,
            database,
            file_ids,
            is_cancelled,
            on_progress,
        )

    def execute(
        self,
        database: Path,
        file_ids: tuple[int, ...],
        *,
        is_cancelled: Callable[[], bool] = _never_cancel,
        on_progress: Callable[[TagWriteProgress], None] = _ignore_progress,
        cover_discovery: CoverDiscovery | None = None,
        cover_choices: tuple[CoverChoice, ...] = (),
    ) -> TagWriteReport:
        """Publish every saved difference in one action, with internal verification."""
        request = TagWriteRequest(database, file_ids, EDIT_FIELDS, allow_date_loss=True)
        try:
            cover_errors: dict[int, str] = {}
            if self.cover_sources is not None:
                discovery = cover_discovery or self.discover_covers(
                    database, file_ids, is_cancelled=is_cancelled, on_progress=on_progress
                )
                if (
                    discovery.database_path != database
                    or discovery.file_ids != file_ids
                    or (discovery.catalog_identity != self.files.identity(database))
                ):
                    raise TagWriteConflict("The selection changed during cover selection.")
                for snapshot in discovery.snapshots:
                    self.catalog.check(database, snapshot)
                    if any(
                        snapshot.file_id in folder.file_ids
                        and snapshot.library_root.resolve() != folder.library_root
                        for folder in discovery.folders
                    ):
                        raise TagWriteConflict("The library changed during cover selection.")
                covers, skipped, cover_errors = resolve_covers(
                    discovery, cover_choices, self.cover_sources, is_cancelled
                )
                request = replace(request, covers=covers, cover_skipped_ids=skipped)
            preview = self.previewer.execute(
                request, is_cancelled=is_cancelled, on_progress=on_progress
            )
            # The catalogue exposes the first USLT text. Update that same version,
            # preserving the remaining languages without requiring another UI choice.
            lyrics = tuple(
                (item.file_id, item.tags.lyrics_keys[0])
                for item in preview.items
                if item.tags is not None
                and len(item.tags.lyrics_keys) > 1
                and item.tags.selected_lyrics is None
            )
            if lyrics:
                preview = self.previewer.execute(
                    replace(request, lyrics_keys=lyrics),
                    is_cancelled=is_cancelled,
                    on_progress=on_progress,
                )
            if self.nfo_writer is not None:
                preview = replace(
                    preview,
                    nfo_items=self.nfo_writer.prepare(
                        preview,
                        is_cancelled,
                        on_progress,
                    ),
                )
            if self.cover_sources is not None:
                preview = replace(
                    preview,
                    cover_folders=discovery.folders,
                    items=tuple(
                        replace(item, state="blocked", message=cover_errors[item.file_id])
                        if item.file_id in cover_errors
                        else item
                        for item in preview.items
                    ),
                )
        except TagWriteCancelled:
            return TagWriteReport(uuid4().hex, (), cancelled=True)
        ready = tuple(item.file_id for item in preview.items if item.state == "ready")
        if ready or any(item.state not in ("absent", "unchanged") for item in preview.nfo_items):
            return self.writer.execute(
                preview, ready, is_cancelled=is_cancelled, on_progress=on_progress
            )
        nfo_results = (
            self.nfo_writer.unchanged_results(preview, is_cancelled)
            if self.nfo_writer is not None
            else ()
        )
        return _cover_results(
            TagWriteReport(
                preview.operation_id,
                tuple(
                    TagWriteResult(
                        item.file_id,
                        item.path,
                        "unchanged"
                        if item.state == "unchanged"
                        else "conflict"
                        if item.state == "conflict"
                        else "failed",
                        item.message,
                    )
                    for item in preview.items
                ),
                cancelled=is_cancelled(),
                nfo_results=nfo_results,
            ),
            preview,
        )
