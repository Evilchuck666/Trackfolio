"""Coordinate view events and asynchronous use cases, without database dependencies."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, cast

from PySide6.QtCore import QObject, QRunnable, Qt, QThreadPool, Signal, Slot
from PySide6.QtWidgets import QFileDialog

from trackfolio.application.catalog import CatalogSession, GetTrack, ListTrackSummaries
from trackfolio.domain.catalog import CatalogEntry, CatalogSummary
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

    def __init__(
        self,
        window: MainWindow,
        opener: Callable[[Path], CatalogSession],
        remember: Callable[[Path], None] | None = None,
    ) -> None:
        super().__init__(window)
        self.window = window
        self._opener = opener
        self._remember = remember
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
        if self._closed:
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

    def open_database(self, path: Path) -> None:
        if self._closed:
            return
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
            return _Opened(session, summaries)

        self._submit(load, "open", self._catalog_token)

    @Slot()
    def refresh(self) -> None:
        if self._closed or self._session is None:
            return
        self._list_token += 1
        session = self._session
        self.window.set_error("")
        self.window.set_status("Actualizando catálogo…")
        self._submit(ListTrackSummaries(session).execute, "list", self._list_token, session)

    @Slot(int)
    def select_track(self, file_id: int) -> None:
        if self._closed or self._session is None:
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
            self.window.set_error(job.task.error)
            self.window.set_status(
                "No se pudo cargar el catálogo."
                if job.kind == "open"
                else "No se pudieron obtener los datos."
            )
        elif job.kind == "open" and isinstance(result, _Opened):
            self._session = result.session
            self._count = len(result.summaries)
            self.window.set_status(self._status())
            self.window.set_catalog(result.session.database_path, result.summaries)
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
        self._pool.clear()
        # Queries have a bounded SQLite timeout. Keep QObject owners alive until work ends.
        self._pool.waitForDone()
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
