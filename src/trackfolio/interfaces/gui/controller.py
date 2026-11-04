"""Coordinate view events and asynchronous use cases, without database dependencies."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from threading import Event
from time import monotonic
from typing import Literal, cast
from uuid import uuid4

from PySide6.QtCore import QObject, QRunnable, Qt, QThreadPool, QTimer, Signal, Slot
from PySide6.QtWidgets import QDialog, QFileDialog, QMessageBox

from trackfolio.application.albums import ListAlbums
from trackfolio.application.catalog import CatalogSession, GetTrack, ListTrackSummaries
from trackfolio.application.edit_catalog import (
    CatalogEditError,
    CatalogEditOutcome,
    CatalogEditSessionFactory,
    CatalogEditValidationError,
    CatalogRecordMissing,
    FindArtists,
    FindGenres,
    GetEditableTrack,
    UpdateCatalogTrack,
    UpdateCatalogTracks,
    validate_batch_edit,
    validate_edit_patch,
)
from trackfolio.application.import_catalog import (
    ImportCatalog,
    ImportProgress,
    ImportReport,
    ImportRequest,
)
from trackfolio.application.write_tags import TagWriteService
from trackfolio.domain.album import Album
from trackfolio.domain.catalog import CatalogEntry, CatalogSummary
from trackfolio.domain.catalog_edit import ArtistChoice, EditableTrack, TrackEditPatch
from trackfolio.domain.tag_write import (
    CoverChoice,
    CoverDiscovery,
    TagWriteProgress,
    TagWriteReport,
)
from trackfolio.interfaces.gui.cover_dialog import CoverChoiceDialog
from trackfolio.interfaces.gui.import_dialog import ImportDialog, ImportProgressDialog
from trackfolio.interfaces.gui.tag_write_dialog import TagWriteDialog
from trackfolio.interfaces.gui.window import MainWindow


class _Signals(QObject):
    completed = Signal(int)


class _Task(QRunnable):
    def __init__(self, identifier: int, operation: Callable[[], object], parent: QObject) -> None:
        super().__init__()
        self.identifier = identifier
        self.operation = operation
        self.signals = _Signals(parent)
        self.result: object = None
        self.error: str | None = None
        self.exception: Exception | None = None

    def run(self) -> None:
        try:
            self.result = self.operation()
        except Exception as exc:
            # The task boundary converts adapter errors into a recoverable view state.
            self.error = str(exc) or type(exc).__name__
            self.exception = exc
        finally:
            self.signals.completed.emit(self.identifier)


@dataclass(frozen=True, slots=True)
class _Opened:
    session: CatalogSession
    summaries: tuple[CatalogSummary, ...]
    selected_id: int | None = None


class _ImportSignals(QObject):
    progress = Signal(int, object)
    completed = Signal(int)


class _ImportTask(QRunnable):
    def __init__(
        self,
        identifier: int,
        importer: ImportCatalog,
        request: ImportRequest,
        cancellation: Event,
        parent: QObject,
    ) -> None:
        super().__init__()
        self.identifier = identifier
        self.importer = importer
        self.request = request
        self.cancellation = cancellation
        self.signals = _ImportSignals(parent)
        self.result: ImportReport | None = None
        self._last_progress = ImportProgress("preparing", 0, None, 0, 0, 0)
        self._last_emitted = 0.0
        self._last_phase = ""

    def _progress(self, progress: ImportProgress) -> None:
        self._last_progress = progress
        now = monotonic()
        if progress.phase != self._last_phase or now - self._last_emitted >= 0.1:
            self._last_phase = progress.phase
            self._last_emitted = now
            self.signals.progress.emit(self.identifier, progress)

    def run(self) -> None:
        try:
            self.result = self.importer.execute(
                self.request,
                is_cancelled=self.cancellation.is_set,
                on_progress=self._progress,
            )
        except Exception:
            # Keep the UI recoverable even for an unexpected adapter/programming failure.
            progress = self._last_progress
            self.result = ImportReport(
                self.request.database_path,
                "failed",
                progress.discovered,
                progress.total,
                progress.created,
                progress.updated,
                progress.failed,
                (),
                "Import ended unexpectedly. Check the catalog before trying again.",
            )
        finally:
            self.signals.completed.emit(self.identifier)


_JobKind = Literal[
    "open",
    "list",
    "detail",
    "edit",
    "save",
    "artists",
    "genres",
    "tag_write",
    "tag_list",
    "tag_covers",
    "albums",
    "album_detail",
    "artist_image",
    "album_edit",
]


@dataclass(slots=True)
class _Job:
    task: _Task
    kind: _JobKind
    catalog_token: int
    request_token: int
    session: CatalogSession | None = None
    selected_id: int | None = None


class CatalogController(QObject):
    catalog_loaded = Signal()
    detail_loaded = Signal(int)
    import_finished = Signal(object)
    edit_started = Signal(int)
    edit_finished = Signal(object)
    tag_progress = Signal(int, object)
    tag_write_finished = Signal(object)

    def __init__(
        self,
        window: MainWindow,
        opener: Callable[[Path], CatalogSession],
        remember: Callable[[Path], None] | None = None,
        importer: ImportCatalog | None = None,
        import_directory: Path | None = None,
        edit_factory: CatalogEditSessionFactory | None = None,
        tag_writer: TagWriteService | None = None,
        artist_image_reader: Callable[[tuple[Album, ...]], bytes | None] | None = None,
    ) -> None:
        super().__init__(window)
        self.window = window
        self._opener = opener
        self._remember = remember
        self._importer = importer
        self._edit_factory = edit_factory
        self._tag_writer = tag_writer
        self._artist_image_reader = artist_image_reader
        self._artist_image_token = 0
        self._tag_dialog: TagWriteDialog | None = None
        self._cover_dialog: CoverChoiceDialog | None = None
        self._tag_running = False
        self._tag_changed = False
        self._tag_token = 0
        self._tag_cancel = Event()
        self._album_list_token = 0
        self._album_detail_token = 0
        self._album_edit = False
        self._edit_snapshot: EditableTrack | None = None
        self._batch_snapshots: tuple[EditableTrack, ...] = ()
        self._edit_path: Path | None = None
        self._displayed_entry: CatalogEntry | None = None
        self._edit_token = 0
        self._save_token = 0
        self._artist_token = 0
        self._genre_token = 0
        self._saving = False
        self._pending_save: (
            tuple[Path, EditableTrack | tuple[EditableTrack, ...], TrackEditPatch] | None
        ) = None
        self._after_save: Callable[[], None] | None = None
        self._import_directory = import_directory or Path.home()
        self._pending_import: ImportRequest | None = None
        self._import_task: _ImportTask | None = None
        self._cancellation = Event()
        self._progress_dialog: ImportProgressDialog | None = None
        self._previous_database: Path | None = None
        self._previous_selection: int | None = None
        self._close_pending = False
        self._open_error_prefix = ""
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(2)
        self._session: CatalogSession | None = None
        self._retired: list[CatalogSession] = []
        self._jobs: dict[int, _Job] = {}
        self._next_identifier = 0
        self._catalog_token = 0
        self._list_token = 0
        self._detail_token = 0
        self._count = 0
        self._closed = False
        window.open_requested.connect(self.choose_catalog)
        window.refresh_requested.connect(self.refresh)
        window.tracks_selected.connect(self.select_tracks)
        window.closing.connect(self.shutdown)
        window.import_requested.connect(self.choose_import)
        window.close_guard = self.request_close
        window.selection_guard = self._allow_selection
        window.selection_group_guard = self._allow_group_selection
        window.edit_requested.connect(self.start_edit)
        window.save_requested.connect(self.save_edit)
        window.cancel_edit_requested.connect(self.cancel_edit)
        window.suggestions_requested.connect(self.find_suggestions)
        window.set_edit_enabled(edit_factory is not None)
        window.set_tag_write_enabled(tag_writer is not None)
        window.write_tags_requested.connect(self.choose_tag_write)
        window.write_all_tags_requested.connect(self.choose_catalog_tag_write)
        self.tag_progress.connect(self._receive_tag_progress, Qt.ConnectionType.QueuedConnection)
        album_view = window.album_view
        album_view.edit_enabled = edit_factory is not None
        album_view.write_enabled = tag_writer is not None
        album_view.album_selected.connect(self.select_album)
        album_view.edit_requested.connect(self.start_album_edit)
        album_view.save_requested.connect(self.save_edit)
        album_view.cancel_requested.connect(self.cancel_edit)
        album_view.write_requested.connect(self.choose_album_tag_write)
        album_view.track_requested.connect(self.open_album_track)
        album_view.selection_guard = lambda key: self._guard_edit(
            lambda: album_view.select_key(key)
        )
        window.view_guard = lambda index: self._guard_edit(
            lambda: window.views.setCurrentIndex(index)
        )
        window.view_changed.connect(self.change_view)
        window.artist_view.album_requested.connect(self.open_artist_album)
        window.artist_view.artist_selected.connect(self.select_artist_image)

    @Slot(object)
    def select_artist_image(self, albums: tuple[Album, ...]) -> None:
        self._artist_image_token += 1
        reader = self._artist_image_reader
        if self._closed or self._session is None or reader is None or not albums:
            return
        self._submit(
            lambda: reader(albums), "artist_image", self._artist_image_token, self._session
        )

    @Slot(int)
    def change_view(self, index: int) -> None:
        if self.window.views.widget(index) in (self.window.album_view, self.window.artist_view):
            self.load_albums()
        elif self.window.current_file_id() is not None:
            self.select_track(cast(int, self.window.current_file_id()))

    @Slot(str)
    def open_artist_album(self, key: str) -> None:
        if not self._guard_edit(lambda: self.open_artist_album(key)):
            return
        self.window.album_view.search.clear()
        self.window.album_view.select_key(key)
        self.window.views.setCurrentWidget(self.window.album_view)

    def load_albums(self) -> None:
        if self._closed or self._session is None or self.saving or self.importing or self.tagging:
            return
        self._album_list_token += 1
        self._album_detail_token += 1
        self._submit(
            ListAlbums(self._session).execute, "albums", self._album_list_token, self._session
        )

    @Slot(object)
    def select_album(self, album: Album | None) -> None:
        if self._closed or self._session is None or self.saving or self.tagging:
            return
        self._edit_token += 1
        self._album_detail_token += 1
        if album is None:
            return
        file_id = next((t.summary.file_id for t in album.tracks if t.has_cover), None)
        session = self._session
        self._submit(
            lambda: session.get(file_id) if file_id is not None else None,
            "album_detail",
            self._album_detail_token,
            session,
        )

    def _finish_album_job(self, job: _Job) -> None:
        view = self.window.album_view
        if job.task.error:
            if job.kind == "album_edit":
                self._album_edit = False
            self.window.set_error(job.task.error)
            return
        if job.kind == "albums":
            view.set_albums(cast(tuple[Album, ...], job.task.result))
            self.window.artist_view.set_albums(cast(tuple[Album, ...], job.task.result))
        elif job.kind == "album_detail":
            entry = cast(CatalogEntry | None, job.task.result)
            view.cover.set_cover(
                entry.metadata.artwork.data if entry and entry.metadata.artwork else None
            )
        else:
            originals = cast(tuple[EditableTrack, ...], job.task.result)
            if not originals or self._session is None:
                self._album_edit = False
                return
            self._album_edit = True
            self._edit_snapshot = originals[0]
            self._batch_snapshots = originals
            self._edit_path = self._session.database_path
            view.begin_edit(originals)
            self.window.set_status("Editing album data · Catalog changes")
            self.edit_started.emit(originals[0].file_id)

    @Slot()
    def start_album_edit(self) -> None:
        view = self.window.album_view
        album = view.current_album
        if (
            self._closed
            or self.saving
            or self.importing
            or self.tagging
            or self._session is None
            or self._edit_factory is None
            or album is None
            or self._edit_snapshot is not None
        ):
            return
        self._edit_token += 1
        self._album_detail_token += 1
        path, factory = self._session.database_path, self._edit_factory

        def load() -> tuple[EditableTrack, ...]:
            reader = factory.open_reader(path)
            try:
                originals = tuple(reader.get_editable(file_id) for file_id in album.file_ids)
                if any(item is None for item in originals):
                    raise CatalogRecordMissing(
                        "An album track no longer exists. Refresh the catalog."
                    )
                return cast(tuple[EditableTrack, ...], originals)
            finally:
                reader.close()

        self._submit(load, "album_edit", self._edit_token, self._session)

    @Slot()
    def choose_album_tag_write(self) -> None:
        album = self.window.album_view.current_album
        if (
            self._closed
            or self.importing
            or self.saving
            or self.tagging
            or self._session is None
            or self._tag_writer is None
            or album is None
        ):
            return
        if not self._guard_edit(self.choose_album_tag_write):
            return
        self._tag_changed = False
        summaries = {song.file_id: song for song in self.window.model.summaries()}
        self._open_tag_dialog(
            self._session.database_path,
            tuple(summaries.get(track.summary.file_id, track.summary) for track in album.tracks),
        )
        if self._tag_dialog is not None:
            self._tag_dialog.setWindowTitle("Write album tags")

    @Slot(int)
    def open_album_track(self, file_id: int) -> None:
        if not self._guard_edit(lambda: self.open_album_track(file_id)):
            return
        self.window.views.setCurrentWidget(self.window.splitter)
        self.window.select_file(file_id)

    @property
    def tagging(self) -> bool:
        return self._tag_dialog is not None or self._tag_running

    @Slot()
    def choose_tag_write(self) -> None:
        if self.window.views.currentWidget() is self.window.artist_view:
            return
        if self.window.views.currentWidget() is self.window.album_view:
            self.choose_album_tag_write()
            return
        if (
            self._closed
            or self._close_pending
            or self.importing
            or self.saving
            or self.tagging
            or self._session is None
            or self._tag_writer is None
            or not self.window.selected_file_ids()
        ):
            return
        if not self._guard_edit(self.choose_tag_write):
            return
        self._list_token += 1
        self._detail_token += 1
        self._edit_token += 1
        self._tag_changed = False
        selected = set(self.window.selected_file_ids())
        songs = tuple(song for song in self.window.model.summaries() if song.file_id in selected)
        self._open_tag_dialog(self._session.database_path, songs)

    @Slot()
    def choose_catalog_tag_write(self) -> None:
        if (
            self._closed
            or self._close_pending
            or self.importing
            or self.saving
            or self.tagging
            or self._session is None
            or self._tag_writer is None
        ):
            return
        if not self._guard_edit(self.choose_catalog_tag_write):
            return
        self._list_token += 1
        self._detail_token += 1
        self._edit_token += 1
        self._tag_changed = False
        self._tag_running = True
        self._tag_token += 1
        self._tag_cancel = Event()
        self.window.set_writing_tags(True)
        self.window.set_error("")
        self.window.set_status("Loading all songs in the catalog…")
        self._submit(
            ListTrackSummaries(self._session).execute,
            "tag_list",
            self._tag_token,
            self._session,
        )

    def _open_tag_dialog(
        self, database: Path, songs: tuple[CatalogSummary, ...], *, all_catalog: bool = False
    ) -> None:
        dialog = TagWriteDialog(database, songs, self.window, all_catalog=all_catalog)
        self._tag_dialog = dialog
        dialog.write_requested.connect(self.write_tags)
        dialog.cancel_requested.connect(self._cancel_tag_write)
        dialog.finished.connect(self._tag_dialog_closed)
        self.window.set_writing_tags(True)
        dialog.show()

    @Slot(int)
    def _tag_dialog_closed(self, _result: int) -> None:
        dialog, self._tag_dialog = self._tag_dialog, None
        if dialog is not None:
            dialog.deleteLater()
        self.window.set_writing_tags(False)
        if self._tag_changed and not self._closed and not self._close_pending:
            self.refresh()

    def _tag_operation(self, operation: Callable[[], object], kind: _JobKind) -> None:
        self._tag_running = True
        self._tag_token += 1
        self._submit(operation, kind, self._tag_token)

    @Slot()
    def write_tags(self) -> None:
        if (
            self._tag_writer is None
            or self._tag_dialog is None
            or self._tag_running
            or self._closed
        ):
            return
        service, dialog = self._tag_writer, self._tag_dialog
        self._tag_cancel = Event()
        if service.cover_sources is not None:
            token = self._tag_token + 1
            self._tag_operation(
                lambda: service.discover_covers(
                    dialog.database_path,
                    dialog.file_ids,
                    is_cancelled=self._tag_cancel.is_set,
                    on_progress=lambda progress: self.tag_progress.emit(token, progress),
                ),
                "tag_covers",
            )
        else:
            self._publish_tags()

    def _cancel_tag_write(self) -> None:
        self._tag_cancel.set()
        if self._cover_dialog is not None:
            self._cover_dialog.reject()

    def _cancel_cover_attempt(self) -> None:
        self._tag_running = False
        report = TagWriteReport(uuid4().hex, (), cancelled=True)
        if self._tag_dialog is not None:
            self._tag_dialog.set_report(report, offer_report=False)
        self.tag_write_finished.emit(report)
        if self._close_pending:
            QTimer.singleShot(0, self._close_when_idle)

    def _publish_tags(
        self,
        discovery: CoverDiscovery | None = None,
        choices: tuple[CoverChoice, ...] = (),
    ) -> None:
        service, dialog = self._tag_writer, self._tag_dialog
        if service is None or dialog is None or self._closed:
            return
        token = self._tag_token + 1
        self._tag_operation(
            lambda: service.execute(
                dialog.database_path,
                dialog.file_ids,
                is_cancelled=self._tag_cancel.is_set,
                on_progress=lambda progress: self.tag_progress.emit(token, progress),
                cover_discovery=discovery,
                cover_choices=choices,
            ),
            "tag_write",
        )

    @Slot(int, object)
    def _receive_tag_progress(self, token: int, progress: TagWriteProgress) -> None:
        if not self._closed and token == self._tag_token and self._tag_dialog is not None:
            self._tag_dialog.set_progress(progress)

    def _finish_tag_job(self, job: _Job) -> None:
        self._tag_running = False
        if job.kind == "tag_covers":
            if self._tag_cancel.is_set() or self._close_pending:
                self._cancel_cover_attempt()
            elif job.task.error:
                if self._tag_dialog is not None:
                    self._tag_dialog.set_error(job.task.error)
            else:
                discovery = cast(CoverDiscovery, job.task.result)
                if any(len(folder.candidates) > 1 for folder in discovery.folders):
                    chooser = CoverChoiceDialog(discovery, self._tag_dialog)
                    self._cover_dialog = chooser
                    self._tag_running = True

                    def chosen(result: int) -> None:
                        self._cover_dialog = None
                        self._tag_running = False
                        if not self._closed:
                            if (
                                result == QDialog.DialogCode.Accepted
                                and not self._tag_cancel.is_set()
                            ):
                                self._publish_tags(discovery, chooser.choices())
                            else:
                                self._cancel_cover_attempt()
                        chooser.deleteLater()

                    chooser.finished.connect(chosen)
                    chooser.open()
                else:
                    self._publish_tags(discovery)
            return
        if job.kind == "tag_list":
            self.window.set_writing_tags(False)
            if self._close_pending:
                self._close_when_idle()
            elif job.task.error:
                self.window.set_error(job.task.error)
                self.window.set_status("Could not load the catalog songs.")
            else:
                songs = cast(tuple[CatalogSummary, ...], job.task.result)
                if songs and job.session is not None:
                    self._open_tag_dialog(job.session.database_path, songs, all_catalog=True)
                else:
                    self.window.set_status("The catalog contains no songs.")
            return
        if job.task.error:
            if self._tag_dialog is not None:
                self._tag_dialog.set_error(job.task.error, offer_report=not self._close_pending)
        else:
            report = cast(TagWriteReport, job.task.result)
            self._tag_changed = self._tag_changed or any(
                item.state in ("confirmed", "catalog_pending") or item.catalog_updated
                for item in report.results
            )
            if self._tag_dialog is not None:
                self._tag_dialog.set_report(report, offer_report=not self._close_pending)
            self.tag_write_finished.emit(report)
        if self._close_pending:
            self._close_when_idle()

    @property
    def saving(self) -> bool:
        return self._saving

    def _reset_edit(self) -> None:
        self._album_edit = False
        self.window.album_view.set_editing(False)
        self._edit_token += 1
        self._artist_token += 1
        self._genre_token += 1
        self._edit_snapshot = None
        self._batch_snapshots = ()
        self._edit_path = None
        self.window.set_edit_state(False)
        self.window.set_detail(self._displayed_entry)

    def _confirm_unsaved(self) -> QMessageBox.StandardButton:
        dialog = QMessageBox(self.window)
        dialog.setWindowTitle("Unsaved changes")
        dialog.setText(
            "These songs have unsaved changes."
            if self._batch_snapshots
            else "This song has unsaved changes."
        )
        dialog.setInformativeText("You can save, discard or continue editing.")
        dialog.setStandardButtons(
            QMessageBox.StandardButton.Save
            | QMessageBox.StandardButton.Discard
            | QMessageBox.StandardButton.Cancel
        )
        dialog.setDefaultButton(QMessageBox.StandardButton.Save)
        for button, label in (
            (QMessageBox.StandardButton.Save, "Save"),
            (QMessageBox.StandardButton.Discard, "Discard"),
            (QMessageBox.StandardButton.Cancel, "Cancel"),
        ):
            widget = dialog.button(button)
            if widget is not None:
                widget.setText(label)
        try:
            return QMessageBox.StandardButton(dialog.exec())
        finally:
            dialog.deleteLater()

    def _guard_edit(self, continuation: Callable[[], None]) -> bool:
        if self.saving:
            return False
        if self._edit_snapshot is None:
            return True
        if not (self.window.album_view.dirty() if self._album_edit else self.window.edit_dirty()):
            self._reset_edit()
            return True
        answer = self._confirm_unsaved()
        if answer == QMessageBox.StandardButton.Discard:
            self._reset_edit()
            return True
        if answer == QMessageBox.StandardButton.Save:
            self._save_edit(continuation)
        return False

    def _allow_selection(self, file_id: int) -> bool:
        return not self.tagging and self._guard_edit(lambda: self.window.select_file(file_id))

    def _allow_group_selection(self, file_ids: tuple[int, ...]) -> bool:
        return not self.tagging and self._guard_edit(lambda: self.window.select_files(file_ids))

    def _request_window_close(self) -> None:
        self.window.close()

    @Slot()
    def start_edit(self) -> None:
        if self.window.views.currentWidget() is self.window.artist_view:
            return
        if self.window.views.currentWidget() is self.window.album_view:
            self.start_album_edit()
            return
        file_id = self.window.current_file_id()
        file_ids = self.window.selected_file_ids()
        if (
            self._closed
            or self._close_pending
            or self.importing
            or self.tagging
            or self.saving
            or self._session is None
            or self._edit_factory is None
            or self._edit_snapshot is not None
            or file_id is None
            or self._displayed_entry is None
        ):
            return
        # A refresh/detail requested before Edit cannot replace the new draft.
        self._list_token += 1
        self._detail_token += 1
        self._edit_token += 1
        token = self._edit_token
        path = self._session.database_path
        factory = self._edit_factory
        self.window.set_error("")
        self.window.set_status("Preparing editor…")

        def load() -> EditableTrack | tuple[EditableTrack, ...] | None:
            session = factory.open_reader(path)
            try:
                if len(file_ids) <= 1:
                    return GetEditableTrack(session).execute(file_id)
                originals = []
                for selected_id in file_ids:
                    item = GetEditableTrack(session).execute(selected_id)
                    if item is None:
                        raise CatalogRecordMissing("A song no longer exists. Refresh the catalog.")
                    originals.append(item)
                return tuple(originals)
            finally:
                session.close()

        self._submit(load, "edit", token, selected_id=file_id)

    @Slot()
    def cancel_edit(self) -> None:
        if self.saving or self._edit_snapshot is None:
            return
        album_edit = self._album_edit
        self._reset_edit()
        if album_edit:
            return
        file_id = self.window.current_file_id()
        if file_id is not None:
            self.select_track(file_id)

    @Slot()
    def save_edit(self) -> None:
        self._save_edit()

    def _save_edit(self, continuation: Callable[[], None] | None = None) -> None:
        if (
            self._closed
            or self._close_pending
            or self.importing
            or self.tagging
            or self.saving
            or self._edit_snapshot is None
            or self._edit_path is None
            or self._edit_factory is None
        ):
            return
        try:
            if self._batch_snapshots:
                patch = (
                    self.window.album_view.patch() if self._album_edit else self.window.edit_patch()
                )
                validate_batch_edit(self._batch_snapshots, patch)
            else:
                patch = validate_edit_patch(self._edit_snapshot.values, self.window.edit_patch())
        except CatalogEditValidationError as exc:
            self.window.set_field_errors({error.field: error.message for error in exc.errors})
            if self._album_edit:
                self.window.album_view.error.setText(str(exc))
            self.window.set_error(str(exc))
            return
        if patch.empty:
            self._reset_edit()
            if continuation is not None:
                continuation()
            return
        self._after_save = continuation
        self._pending_save = (self._edit_path, self._batch_snapshots or self._edit_snapshot, patch)
        self._saving = True
        self._save_token += 1
        self._list_token += 1
        self._detail_token += 1
        self._edit_token += 1
        self._artist_token += 1
        self._genre_token += 1
        self.window.set_edit_state(not self._album_edit, saving=True)
        self.window.set_error("")
        self.window.set_status("Saving changes…")
        self._begin_save_when_idle()

    def _begin_save_when_idle(self) -> None:
        if self._closed or self._pending_save is None:
            return
        if self._jobs:
            return
        if self._pool.activeThreadCount():
            QTimer.singleShot(10, self._begin_save_when_idle)
            return
        self._collect_retired()
        path, original, patch = self._pending_save
        self._pending_save = None
        assert self._edit_factory is not None
        if isinstance(original, tuple):
            batch_updater = UpdateCatalogTracks(self._edit_factory)
            self._submit(
                lambda: batch_updater.execute(path, original, patch),
                "save",
                self._save_token,
                selected_id=original[0].file_id,
            )
        else:
            updater = UpdateCatalogTrack(self._edit_factory)
            self._submit(
                lambda: updater.execute(path, original, patch),
                "save",
                self._save_token,
                selected_id=original.file_id,
            )

    @Slot(str, str)
    def find_suggestions(self, field: str, query: str) -> None:
        if (
            self._closed
            or self.saving
            or self._edit_snapshot is None
            or self._edit_path is None
            or self._edit_factory is None
            or field not in ("artists", "genres")
        ):
            return
        path, factory = self._edit_path, self._edit_factory
        if field == "artists":
            self._artist_token += 1
            token = self._artist_token
        else:
            self._genre_token += 1
            token = self._genre_token

        def find() -> tuple[ArtistChoice, ...] | tuple[str, ...]:
            session = factory.open_reader(path)
            try:
                if field == "artists":
                    return FindArtists(session).execute(query)
                return FindGenres(session).execute(query)
            finally:
                session.close()

        self._submit(find, cast(_JobKind, field), token)

    @property
    def importing(self) -> bool:
        return self._pending_import is not None or self._import_task is not None

    @Slot()
    def choose_import(self) -> None:
        if (
            self._closed
            or self._close_pending
            or self.importing
            or self.tagging
            or self.saving
            or self._importer is None
        ):
            return
        if not self._guard_edit(self.choose_import):
            return
        current = self._session.database_path if self._session is not None else None
        dialog = ImportDialog(self.window, current, self._import_directory)
        try:
            if dialog.exec() == QFileDialog.DialogCode.Accepted:
                request = dialog.request()
                if request is not None:
                    self.start_import(request)
        finally:
            dialog.deleteLater()

    def start_import(self, request: ImportRequest) -> None:
        if (
            self._closed
            or self._close_pending
            or self.importing
            or self.tagging
            or self.saving
            or self._importer is None
        ):
            return
        if not self._guard_edit(lambda: self.start_import(request)):
            return
        self._edit_token += 1
        self._displayed_entry = None
        self._pending_import = request
        self._cancellation = Event()
        self._previous_database = self._session.database_path if self._session is not None else None
        self._previous_selection = self.window.current_file_id()
        self._catalog_token += 1
        self._list_token += 1
        self._detail_token += 1
        if self._session is not None:
            self._retired.append(self._session)
            self._session = None
        self.window.set_importing(True)
        self.window.set_error("")
        self.window.set_status("Preparing import…")
        if self._progress_dialog is not None:
            self._progress_dialog.close()
            self._progress_dialog.deleteLater()
        self._progress_dialog = ImportProgressDialog(self.window)
        self._progress_dialog.cancel_requested.connect(self.cancel_import)
        self._progress_dialog.show()
        self._begin_import_when_idle()

    def _begin_import_when_idle(self) -> None:
        if self._closed or self._pending_import is None or self._import_task is not None:
            return
        if self._jobs:
            return
        # A completion signal can arrive just before QRunnable.run returns.
        if self._pool.activeThreadCount():
            QTimer.singleShot(10, self._begin_import_when_idle)
            return
        self._collect_retired()
        request = self._pending_import
        if self._cancellation.is_set():
            self._finish_import(
                ImportReport(request.database_path, "cancelled", 0, None, 0, 0, 0, ())
            )
            return
        assert self._importer is not None
        self._next_identifier += 1
        task = _ImportTask(self._next_identifier, self._importer, request, self._cancellation, self)
        self._import_task = task
        task.signals.progress.connect(self._import_progress, Qt.ConnectionType.QueuedConnection)
        task.signals.completed.connect(self._import_completed, Qt.ConnectionType.QueuedConnection)
        self._pool.start(task)

    @Slot()
    def cancel_import(self) -> None:
        if not self.importing:
            return
        self._cancellation.set()
        if self._progress_dialog is not None:
            self._progress_dialog.set_cancelling()
        self.window.set_status("Cancelling import…")

    @Slot(int, object)
    def _import_progress(self, identifier: int, progress: ImportProgress) -> None:
        if self._closed or self._import_task is None:
            return
        if (
            identifier == self._import_task.identifier
            and not self._cancellation.is_set()
            and self._progress_dialog is not None
        ):
            self._progress_dialog.set_progress(progress)

    @Slot(int)
    def _import_completed(self, identifier: int) -> None:
        task = self._import_task
        if self._closed or task is None or identifier != task.identifier:
            return
        assert task.result is not None
        task.signals.deleteLater()
        self._finish_import(task.result)

    def _finish_import(self, report: ImportReport) -> None:
        self._pending_import = None
        self._import_task = None
        self.window.set_importing(False)
        if self._progress_dialog is not None:
            self._progress_dialog.set_report(report)
        if self._close_pending:
            self._close_when_idle()
            self.import_finished.emit(report)
            return
        destination = report.database_path if report.saved else self._previous_database
        if destination is not None:
            selected = self._previous_selection if destination == self._previous_database else None
            self.open_database(
                destination,
                selected_id=selected,
                error_prefix=(
                    "The music was saved, but the resulting catalog could not be opened. "
                    if report.saved
                    else ""
                ),
            )
        else:
            self.window.set_status("No songs were saved. You can import music again.")
            self.window.set_error(report.fatal_error or "")
        self._update_busy()
        # Observers can synchronously start another operation or close the window.
        # Emit only after restoring a consistent controller/view state.
        self.import_finished.emit(report)

    def request_close(self) -> bool:
        if self._closed:
            return True
        if self._tag_running:
            self._close_pending = True
            self._cancel_tag_write()
            return False
        if self._tag_dialog is not None:
            self._tag_dialog.reject()
        if self.saving:
            self._close_pending = True
            return False
        if not self._guard_edit(self._request_window_close):
            return False
        if not self.importing:
            return True
        self._close_pending = True
        self.cancel_import()
        return False

    def _close_when_idle(self) -> None:
        if self._closed:
            return
        if (
            self._pool.activeThreadCount()
            or self._jobs
            or self.importing
            or self.saving
            or self._tag_running
        ):
            QTimer.singleShot(10, self._close_when_idle)
        else:
            self.window.close()

    def _submit(
        self,
        operation: Callable[[], object],
        kind: _JobKind,
        request_token: int,
        session: CatalogSession | None = None,
        selected_id: int | None = None,
    ) -> None:
        self._next_identifier += 1
        task = _Task(self._next_identifier, operation, self)
        job = _Job(task, kind, self._catalog_token, request_token, session, selected_id)
        self._jobs[task.identifier] = job
        task.signals.completed.connect(self._finished, Qt.ConnectionType.QueuedConnection)
        self._pool.start(task)
        self._update_busy()

    @Slot()
    def choose_catalog(self) -> None:
        if self._closed or self._close_pending or self.importing or self.saving or self.tagging:
            return
        if not self._guard_edit(self.choose_catalog):
            return
        dialog = QFileDialog(self.window, "Open Trackfolio catalog")
        dialog.setOption(QFileDialog.Option.DontUseNativeDialog, True)
        dialog.setFileMode(QFileDialog.FileMode.ExistingFile)
        dialog.setNameFilters(
            ["Trackfolio catalogs (*.tfo *.sqlite3 *.sqlite *.db)", "All files (*)"]
        )
        if self._session is not None:
            dialog.setDirectory(str(self._session.database_path.parent))
        if dialog.exec() == QFileDialog.DialogCode.Accepted:
            selected = dialog.selectedFiles()
            if selected:
                self.open_database(Path(selected[0]))

    def open_database(
        self, path: Path, *, selected_id: int | None = None, error_prefix: str = ""
    ) -> None:
        if self._closed or self._close_pending or self.importing or self.saving or self.tagging:
            return
        if not self._guard_edit(
            lambda: self.open_database(path, selected_id=selected_id, error_prefix=error_prefix)
        ):
            return
        self._edit_token += 1
        self._displayed_entry = None
        self._open_error_prefix = error_prefix
        self._catalog_token += 1
        self._list_token += 1
        self._detail_token += 1
        if self._session is not None:
            self._retired.append(self._session)
            self._session = None
        self._collect_retired()
        self._count = 0
        self.window.set_error("")
        self.window.set_catalog(None, ())
        self.window.set_detail(None)
        self.window.set_status("Opening catalog…")

        def load() -> _Opened:
            session = self._opener(path)
            try:
                summaries = ListTrackSummaries(session).execute()
            except Exception:
                session.close()
                raise
            return _Opened(session, summaries, selected_id)

        self._submit(load, "open", self._catalog_token)

    @Slot()
    def refresh(self) -> None:
        if self._closed or self.importing or self.saving or self.tagging or self._session is None:
            return
        if not self._guard_edit(self.refresh):
            return
        self._edit_token += 1
        self._list_token += 1
        session = self._session
        self.window.set_error("")
        self.window.set_status("Refreshing catalog…")
        self._submit(ListTrackSummaries(session).execute, "list", self._list_token, session)

    @Slot(object)
    def select_tracks(self, file_ids: tuple[int, ...]) -> None:
        if file_ids:
            self.select_track(file_ids[0])
        else:
            self._edit_token += 1
            self._detail_token += 1
            self._displayed_entry = None
            self.window.set_detail(None)

    @Slot(int)
    def select_track(self, file_id: int) -> None:
        if self._closed or self.importing or self.saving or self.tagging or self._session is None:
            return
        if not self._guard_edit(lambda: self.window.select_file(file_id)):
            return
        self._edit_token += 1
        self._displayed_entry = None
        self._detail_token += 1
        session = self._session
        token = self._detail_token
        self.window.set_detail(None)
        self.window.set_error("")
        self.window.set_status("Loading metadata…")

        def load() -> CatalogEntry | None:
            # A superseded queued task can finish without opening another connection.
            if self._closed or token != self._detail_token:
                return None
            return GetTrack(session).execute(file_id)

        self._submit(load, "detail", token, session, file_id)

    def _is_current(self, job: _Job) -> bool:
        if self._closed:
            return False
        if job.catalog_token != self._catalog_token:
            return False
        token = {
            "open": self._catalog_token,
            "list": self._list_token,
            "detail": self._detail_token,
            "edit": self._edit_token,
            "save": self._save_token,
            "artists": self._artist_token,
            "genres": self._genre_token,
            "tag_write": self._tag_token,
            "tag_list": self._tag_token,
            "tag_covers": self._tag_token,
            "albums": self._album_list_token,
            "album_detail": self._album_detail_token,
            "artist_image": self._artist_image_token,
            "album_edit": self._edit_token,
        }
        return job.request_token == token[job.kind]

    @Slot(int)
    def _finished(self, identifier: int) -> None:
        job = self._jobs.pop(identifier, None)
        if job is None:
            return
        result = job.task.result
        if not self._is_current(job):
            if isinstance(result, _Opened):
                result.session.close()
        elif job.kind in ("tag_write", "tag_list", "tag_covers"):
            self._finish_tag_job(job)
        elif job.kind == "artist_image":
            self.window.artist_view.cover.set_cover(
                cast(bytes | None, job.task.result) if not job.task.error else None
            )
        elif job.kind in ("albums", "album_detail", "album_edit"):
            self._finish_album_job(job)
        elif job.kind == "save":
            self._finish_save(job)
        elif job.task.error is not None:
            self.window.set_error(
                (self._open_error_prefix if job.kind == "open" else "") + job.task.error
            )
            self.window.set_status(
                "Could not load the catalog."
                if job.kind == "open"
                else "Could not retrieve the data."
            )
        elif job.kind == "open" and isinstance(result, _Opened):
            self._session = result.session
            self._count = len(result.summaries)
            self.window.set_status(self._status())
            self.window.set_catalog(
                result.session.database_path, result.summaries, result.selected_id
            )
            if self._remember is not None:
                try:
                    self._remember(result.session.database_path)
                except OSError as exc:
                    self.window.set_error(f"Could not save the catalog preference: {exc}")
            if self.window.views.currentWidget() in (
                self.window.album_view,
                self.window.artist_view,
            ):
                self.load_albums()
            self.catalog_loaded.emit()
        elif job.kind == "list" and self._session is not None:
            # An empty refreshed list emits no selection event to supersede an old detail.
            self._detail_token += 1
            self._edit_token += 1
            self._displayed_entry = None
            summaries = cast(tuple[CatalogSummary, ...], result)
            self._count = len(summaries)
            self.window.set_status(self._status())
            self.window.set_catalog(
                self._session.database_path,
                summaries,
                self.window.current_file_id(),
                selected_file_ids=self.window.selected_file_ids(),
            )
            if self.window.views.currentWidget() in (
                self.window.album_view,
                self.window.artist_view,
            ):
                self.load_albums()
            self.catalog_loaded.emit()
        elif job.kind == "detail":
            entry = cast(CatalogEntry | None, result)
            self._displayed_entry = entry
            self.window.set_detail(entry)
            self.window.set_status(
                self._status()
                if entry is not None
                else "The record is no longer available. Refresh the catalog."
            )
            self.detail_loaded.emit(job.selected_id)
        elif job.kind == "edit" and isinstance(result, tuple) and self._session is not None:
            originals = cast(tuple[EditableTrack, ...], result)
            self._batch_snapshots = originals
            self._edit_snapshot = originals[0]
            self._edit_path = self._session.database_path
            self.window.begin_batch_edit(tuple(item.values for item in originals))
            self.window.set_status(f"Editing {len(originals)} songs · Catalog changes")
            self.edit_started.emit(originals[0].file_id)
            self.find_suggestions("artists", "")
            self.find_suggestions("genres", "")
        elif job.kind == "edit" and isinstance(result, EditableTrack) and self._session is not None:
            self._edit_snapshot = result
            self._edit_path = self._session.database_path
            self.window.begin_edit(result.values)
            self.window.set_status("Editing song · Catalog changes")
            self.edit_started.emit(result.file_id)
            self.find_suggestions("artists", "")
            self.find_suggestions("genres", "")
        elif job.kind == "edit":
            self.window.set_error("The song is no longer available. Refresh the catalog.")
        elif job.kind in ("artists", "genres"):
            if job.kind == "artists":
                choices = tuple(choice.name for choice in cast(tuple[ArtistChoice, ...], result))
            else:
                choices = cast(tuple[str, ...], result)
            self.window.set_suggestions(job.kind, choices)
        job.task.signals.deleteLater()
        self._collect_retired()
        self._update_busy()
        self._begin_import_when_idle()
        self._begin_save_when_idle()

    def _finish_save(self, job: _Job) -> None:
        album_edit = self._album_edit
        self._saving = False
        continuation = self._after_save
        self._after_save = None
        if job.task.error is not None:
            self._close_pending = False
            self.window.set_edit_state(not album_edit)
            if album_edit:
                self.window.album_view.error.setText(job.task.error)
            error = job.task.exception
            if isinstance(error, CatalogEditValidationError):
                self.window.set_field_errors({item.field: item.message for item in error.errors})
            message = job.task.error
            if isinstance(error, CatalogEditError) and error.backup_path is not None:
                message += f" Previous backup: {error.backup_path}"
            self.window.set_error(message)
            self.window.set_status("Changes were not saved. The draft is preserved.")
            self.edit_finished.emit(None)
            return
        result = job.task.result
        outcomes = (
            cast(tuple[CatalogEditOutcome, ...], result)
            if isinstance(result, tuple)
            else (result,)
            if isinstance(result, CatalogEditOutcome)
            else ()
        )
        self._reset_edit()
        for saved in outcomes:
            self.window.model.update_summary(saved.summary)
        if outcomes:
            first = outcomes[0]
            self._displayed_entry = first.entry
            self.window.set_detail(first.entry)
            self.window.set_error(next((item.warning for item in outcomes if item.warning), ""))
            message = (
                f"Changes saved to {len(outcomes)} songs."
                if len(outcomes) > 1
                else "Changes saved to the catalog."
            )
            if first.backup_path is not None:
                message += f" Previous backup: {first.backup_path}"
            self.window.set_status(message)
        else:
            self.window.set_status("No changes to save.")
        outcome = result
        if album_edit and not self._close_pending:
            self.load_albums()
        if self._close_pending:
            self._close_when_idle()
        generation = (
            self._catalog_token,
            self._list_token,
            self._detail_token,
            self._edit_token,
            self._save_token,
        )
        self.edit_finished.emit(outcome)
        if continuation is not None:

            def continue_if_current() -> None:
                current = (
                    self._catalog_token,
                    self._list_token,
                    self._detail_token,
                    self._edit_token,
                    self._save_token,
                )
                if not self._closed and not self._close_pending and current == generation:
                    continuation()

            QTimer.singleShot(0, continue_if_current)

    def _status(self) -> str:
        if self._session is None:
            return "Open a catalog to browse your music."
        noun = "song" if self._count == 1 else "songs"
        return f"{self._count} {noun} · {self._session.database_path}"

    def _update_busy(self) -> None:
        if not self._closed:
            self.window.set_busy(
                any(
                    self._is_current(job) and job.kind not in ("artists", "genres")
                    for job in self._jobs.values()
                )
            )

    def _collect_retired(self) -> None:
        retained = []
        for session in self._retired:
            if any(job.session is session for job in self._jobs.values()):
                retained.append(session)
            else:
                session.close()
        self._retired = retained

    @Slot()
    def shutdown(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._cancellation.set()
        self._cancel_tag_write()
        # This synchronous drain is for final teardown after the event loop has stopped.
        # Normal window closure during import uses request_close and keeps events flowing.
        self._pool.clear()
        # Queries have a bounded SQLite timeout. Keep QObject owners alive until work ends.
        self._pool.waitForDone()
        self._tag_running = False
        if self._tag_dialog is not None:
            self._tag_dialog.set_busy(False)
            self._tag_dialog.reject()
        if self._import_task is not None:
            self._import_task.signals.deleteLater()
        self._import_task = None
        self._pending_import = None
        self._pending_save = None
        self._after_save = None
        self._saving = False
        for job in self._jobs.values():
            if isinstance(job.task.result, _Opened):
                job.task.result.session.close()
            job.task.signals.deleteLater()
        self._jobs.clear()
        if self._session is not None:
            self._session.close()
            self._session = None
        for session in self._retired:
            session.close()
        self._retired.clear()
