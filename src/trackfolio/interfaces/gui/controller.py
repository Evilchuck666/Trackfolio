"""Coordinate view events and asynchronous use cases, without database dependencies."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from threading import Event
from time import monotonic
from typing import Literal, cast

from PySide6.QtCore import QObject, QRunnable, Qt, QThreadPool, QTimer, Signal, Slot
from PySide6.QtWidgets import QFileDialog

from trackfolio.application.catalog import CatalogSession, GetTrack, ListTrackSummaries
from trackfolio.application.import_catalog import (
    ImportCatalog,
    ImportProgress,
    ImportReport,
    ImportRequest,
)
from trackfolio.domain.catalog import CatalogEntry, CatalogSummary
from trackfolio.interfaces.gui.import_dialog import ImportDialog, ImportProgressDialog
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

    def run(self) -> None:
        try:
            self.result = self.operation()
        except Exception as exc:
            # The task boundary converts adapter errors into a recoverable view state.
            self.error = str(exc) or type(exc).__name__
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
                "La importación terminó inesperadamente. Comprueba el catálogo antes de repetirla.",
            )
        finally:
            self.signals.completed.emit(self.identifier)


@dataclass(slots=True)
class _Job:
    task: _Task
    kind: Literal["open", "list", "detail"]
    catalog_token: int
    request_token: int
    session: CatalogSession | None = None
    selected_id: int | None = None


class CatalogController(QObject):
    catalog_loaded = Signal()
    detail_loaded = Signal(int)
    import_finished = Signal(object)

    def __init__(
        self,
        window: MainWindow,
        opener: Callable[[Path], CatalogSession],
        remember: Callable[[Path], None] | None = None,
        importer: ImportCatalog | None = None,
        import_directory: Path | None = None,
    ) -> None:
        super().__init__(window)
        self.window = window
        self._opener = opener
        self._remember = remember
        self._importer = importer
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
        window.track_selected.connect(self.select_track)
        window.closing.connect(self.shutdown)
        window.import_requested.connect(self.choose_import)
        window.close_guard = self.request_close

    @property
    def importing(self) -> bool:
        return self._pending_import is not None or self._import_task is not None

    @Slot()
    def choose_import(self) -> None:
        if self._closed or self._close_pending or self.importing or self._importer is None:
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
        if self._closed or self._close_pending or self.importing or self._importer is None:
            return
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
        self.window.set_status("Preparando importación…")
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
        self.window.set_status("Cancelando importación…")

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
                    "La música se guardó, pero no se pudo abrir el catálogo resultante. "
                    if report.saved
                    else ""
                ),
            )
        else:
            self.window.set_status("No se guardaron canciones. Puedes volver a importar música.")
            self.window.set_error(report.fatal_error or "")
        self._update_busy()
        # Observers can synchronously start another operation or close the window.
        # Emit only after restoring a consistent controller/view state.
        self.import_finished.emit(report)

    def request_close(self) -> bool:
        if self._closed or not self.importing:
            return True
        self._close_pending = True
        self.cancel_import()
        return False

    def _close_when_idle(self) -> None:
        if self._closed:
            return
        if self._pool.activeThreadCount() or self._jobs or self.importing:
            QTimer.singleShot(10, self._close_when_idle)
        else:
            self.window.close()

    def _submit(
        self,
        operation: Callable[[], object],
        kind: Literal["open", "list", "detail"],
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
        if self._closed or self._close_pending or self.importing:
            return
        dialog = QFileDialog(self.window, "Abrir catálogo de Trackfolio")
        dialog.setOption(QFileDialog.Option.DontUseNativeDialog, True)
        dialog.setFileMode(QFileDialog.FileMode.ExistingFile)
        dialog.setNameFilters(
            ["Catálogos de Trackfolio (*.tfo *.sqlite3 *.sqlite *.db)", "Todos los archivos (*)"]
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
        if self._closed or self._close_pending or self.importing:
            return
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
        self.window.set_status("Abriendo catálogo…")

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
        if self._closed or self.importing or self._session is None:
            return
        self._list_token += 1
        session = self._session
        self.window.set_error("")
        self.window.set_status("Actualizando catálogo…")
        self._submit(ListTrackSummaries(session).execute, "list", self._list_token, session)

    @Slot(int)
    def select_track(self, file_id: int) -> None:
        if self._closed or self.importing or self._session is None:
            return
        self._detail_token += 1
        session = self._session
        token = self._detail_token
        self.window.set_detail(None)
        self.window.set_error("")
        self.window.set_status("Cargando metadatos…")

        def load() -> CatalogEntry | None:
            # A superseded queued task can finish without opening another connection.
            if self._closed or token != self._detail_token:
                return None
            return GetTrack(session).execute(file_id)

        self._submit(load, "detail", token, session, file_id)

    def _is_current(self, job: _Job) -> bool:
        if self._closed or job.catalog_token != self._catalog_token:
            return False
        token = {
            "open": self._catalog_token,
            "list": self._list_token,
            "detail": self._detail_token,
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
        elif job.task.error is not None:
            self.window.set_error(
                (self._open_error_prefix if job.kind == "open" else "") + job.task.error
            )
            self.window.set_status(
                "No se pudo cargar el catálogo."
                if job.kind == "open"
                else "No se pudieron obtener los datos."
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
                    self.window.set_error(f"No se pudo guardar la preferencia del catálogo: {exc}")
            self.catalog_loaded.emit()
        elif job.kind == "list" and self._session is not None:
            # An empty refreshed list emits no selection event to supersede an old detail.
            self._detail_token += 1
            summaries = cast(tuple[CatalogSummary, ...], result)
            self._count = len(summaries)
            self.window.set_status(self._status())
            self.window.set_catalog(
                self._session.database_path, summaries, self.window.current_file_id()
            )
            self.catalog_loaded.emit()
        elif job.kind == "detail":
            entry = cast(CatalogEntry | None, result)
            self.window.set_detail(entry)
            self.window.set_status(
                self._status()
                if entry is not None
                else "El registro ya no está disponible. Actualiza el catálogo."
            )
            self.detail_loaded.emit(job.selected_id)
        job.task.signals.deleteLater()
        self._collect_retired()
        self._update_busy()
        self._begin_import_when_idle()

    def _status(self) -> str:
        if self._session is None:
            return "Abre un catálogo para consultar tu música."
        noun = "canción" if self._count == 1 else "canciones"
        return f"{self._count} {noun} · {self._session.database_path}"

    def _update_busy(self) -> None:
        if not self._closed:
            self.window.set_busy(any(self._is_current(job) for job in self._jobs.values()))

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
        # This synchronous drain is for final teardown after the event loop has stopped.
        # Normal window closure during import uses request_close and keeps events flowing.
        self._pool.clear()
        # Queries have a bounded SQLite timeout. Keep QObject owners alive until work ends.
        self._pool.waitForDone()
        if self._import_task is not None:
            self._import_task.signals.deleteLater()
        self._import_task = None
        self._pending_import = None
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
