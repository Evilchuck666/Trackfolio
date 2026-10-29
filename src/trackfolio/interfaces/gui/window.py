"""The catalog window: Qt widgets render values and emit user intentions."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import cast

from PySide6.QtCore import QEvent, QModelIndex, QObject, QPoint, QRect, QSignalBlocker, Qt, Signal
from PySide6.QtGui import (
    QAction,
    QCloseEvent,
    QGuiApplication,
    QKeyEvent,
    QKeySequence,
    QMouseEvent,
    QPixmap,
    QResizeEvent,
    QShortcut,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QTableView,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from trackfolio.domain.catalog import CatalogEntry, CatalogSummary
from trackfolio.domain.catalog_edit import EditableValues, EditField, FieldChange, TrackEditPatch
from trackfolio.interfaces.gui.catalog_model import CatalogTableModel
from trackfolio.interfaces.gui.ordered_labels import OrderedLabels
from trackfolio.interfaces.gui.theme import icon


class CoverLabel(QLabel):
    """Scale a cover from the catalog, preserving aspect ratio at each screen scale."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("Cover")
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setFixedSize(184, 184)
        self.setAccessibleName("Portada del álbum")
        self._original = QPixmap()

    def set_cover(self, data: bytes | None) -> None:
        self._original = QPixmap()
        if data is not None:
            self._original.loadFromData(data)
        self._redraw()

    def _redraw(self) -> None:
        if self._original.isNull():
            self.clear()
            return
        ratio = self.devicePixelRatioF()
        scaled = self._original.scaled(
            self.size() * ratio,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        scaled.setDevicePixelRatio(ratio)
        self.setPixmap(scaled)

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._redraw()

    def event(self, event: QEvent) -> bool:
        result = super().event(event)
        if event.type() == QEvent.Type.DevicePixelRatioChange and hasattr(self, "_original"):
            self._redraw()
        return result


class TitleBar(QWidget):
    """A shared title bar using system move operations where the backend supports them."""

    def __init__(self, window: MainWindow) -> None:
        super().__init__(window)
        self._window = window
        self._drag_start: QPoint | None = None
        self._window_start = QPoint()
        self.setObjectName("TitleBar")
        self.setFixedHeight(48)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(18, 0, 8, 0)
        layout.setSpacing(10)
        brand = QLabel(self)
        brand.setPixmap(icon("app").pixmap(24, 24))
        brand.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        layout.addWidget(brand)
        title = QLabel("Trackfolio", self)
        title.setObjectName("BrandTitle")
        title.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        layout.addWidget(title)
        layout.addStretch()
        self.minimize_button = self._button("minimize", "Minimizar", window.showMinimized)
        self.maximize_button = self._button("maximize", "Maximizar", window.toggle_maximized)
        self.close_button = self._button("close", "Cerrar", window.close)
        self.close_button.setObjectName("CloseButton")
        for button in (self.minimize_button, self.maximize_button, self.close_button):
            layout.addWidget(button)

    def _button(self, name: str, label: str, callback: Callable[[], object]) -> QToolButton:
        button = QToolButton(self)
        button.setIcon(icon(name))
        button.setToolTip(label)
        button.setAccessibleName(label)
        button.setFixedSize(38, 32)
        button.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        button.clicked.connect(callback)
        return button

    def sync_window_state(self) -> None:
        maximized = self._window.isMaximized()
        self.maximize_button.setIcon(icon("restore" if maximized else "maximize"))
        label = "Restaurar" if maximized else "Maximizar"
        self.maximize_button.setToolTip(label)
        self.maximize_button.setAccessibleName(label)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            handle = self._window.windowHandle()
            if handle is not None and handle.startSystemMove():
                event.accept()
                return
            if self._window.needs_system_frame():
                self._window.use_system_frame()
                event.accept()
                return
            self._drag_start = event.globalPosition().toPoint()
            self._window_start = self._window.pos()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._drag_start is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self._window.move(
                self._window_start + event.globalPosition().toPoint() - self._drag_start
            )
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        self._drag_start = None
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._window.toggle_maximized()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)


class ResizeHandle(QWidget):
    """Thin edge hit targets, with a fallback for backends lacking system resize."""

    def __init__(self, window: MainWindow, edges: Qt.Edge, cursor: Qt.CursorShape) -> None:
        super().__init__(window)
        self._window = window
        self._edges = edges
        self._drag_start: QPoint | None = None
        self._original_geometry = QRect()
        self.setCursor(cursor)
        self.setObjectName("ResizeHandle")

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton and not self._window.isMaximized():
            handle = self._window.windowHandle()
            if handle is not None and handle.startSystemResize(self._edges):
                event.accept()
                return
            if self._window.needs_system_frame():
                self._window.use_system_frame()
                event.accept()
                return
            self._drag_start = event.globalPosition().toPoint()
            self._original_geometry = self._window.geometry()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._drag_start is None or not event.buttons() & Qt.MouseButton.LeftButton:
            super().mouseMoveEvent(event)
            return
        delta = event.globalPosition().toPoint() - self._drag_start
        geometry = QRect(self._original_geometry)
        minimum_width = self._window.minimumWidth() - 1
        minimum_height = self._window.minimumHeight() - 1
        if self._edges & Qt.Edge.LeftEdge:
            geometry.setLeft(min(geometry.left() + delta.x(), geometry.right() - minimum_width))
        if self._edges & Qt.Edge.RightEdge:
            geometry.setRight(max(geometry.right() + delta.x(), geometry.left() + minimum_width))
        if self._edges & Qt.Edge.TopEdge:
            geometry.setTop(min(geometry.top() + delta.y(), geometry.bottom() - minimum_height))
        if self._edges & Qt.Edge.BottomEdge:
            geometry.setBottom(max(geometry.bottom() + delta.y(), geometry.top() + minimum_height))
        self._window.setGeometry(geometry)
        event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        self._drag_start = None
        super().mouseReleaseEvent(event)


class MainWindow(QMainWindow):
    """Show catalog data and emit user intentions without persistence knowledge."""

    open_requested = Signal()
    import_requested = Signal()
    refresh_requested = Signal()
    track_selected = Signal(int)
    edit_requested = Signal()
    save_requested = Signal()
    cancel_edit_requested = Signal()
    dirty_changed = Signal(bool)
    suggestions_requested = Signal(str, str)
    closing = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("MainWindow")
        self.setWindowTitle("Trackfolio")
        self.setWindowIcon(icon("app"))
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint)
        self.quit_shortcut = QShortcut(QKeySequence(QKeySequence.StandardKey.Quit), self)
        self.quit_shortcut.activated.connect(self.close)
        self.resize(1320, 840)
        self.setMinimumSize(960, 640)
        self._catalog_path: Path | None = None
        self._busy = False
        self._importing = False
        self.close_guard: Callable[[], bool] | None = None
        self.selection_guard: Callable[[int], bool] | None = None
        self._current_file_id: int | None = None
        self._detail_loaded = False
        self._edit_enabled = False
        self._editing = False
        self._saving = False
        self._updating_edit = False
        self._edit_values: EditableValues | None = None
        self._edit_valid = True
        self._dirty = False
        self._system_frame = False
        self.fields: dict[str, QLineEdit] = {}
        self.field_errors: dict[str, QLabel] = {}
        self.ordered_labels: dict[str, OrderedLabels] = {}

        shell = QWidget(self)
        shell.setObjectName("WindowShell")
        self.setCentralWidget(shell)
        layout = QVBoxLayout(shell)
        layout.setContentsMargins(1, 1, 1, 1)
        layout.setSpacing(0)
        self.title_bar = TitleBar(self)
        layout.addWidget(self.title_bar)

        content = QWidget(shell)
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(24, 20, 24, 16)
        content_layout.setSpacing(18)
        layout.addWidget(content, 1)
        self._build_toolbar(content_layout)
        self.error_label = QLabel(content)
        self.error_label.setObjectName("ErrorMessage")
        self.error_label.setWordWrap(True)
        self.error_label.setTextFormat(Qt.TextFormat.PlainText)
        self.error_label.hide()
        content_layout.addWidget(self.error_label)

        self.splitter = QSplitter(Qt.Orientation.Horizontal, content)
        self.splitter.setChildrenCollapsible(False)
        self.splitter.setHandleWidth(14)
        self.splitter.addWidget(self._build_catalog())
        self.splitter.addWidget(self._build_detail())
        self.splitter.setStretchFactor(0, 1)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setSizes([620, 620])
        content_layout.addWidget(self.splitter, 1)

        footer = QHBoxLayout()
        self.status_label = QLabel("Abre un catálogo o importa música para comenzar.", content)
        self.status_label.setObjectName("StatusLabel")
        self.status_label.setTextFormat(Qt.TextFormat.PlainText)
        self.status_label.setWordWrap(True)
        self.catalog_label = QLabel(content)
        self.catalog_label.setObjectName("StatusLabel")
        self.catalog_label.setTextFormat(Qt.TextFormat.PlainText)
        footer.addWidget(self.status_label, 1)
        footer.addWidget(self.catalog_label)
        content_layout.addLayout(footer)
        self._handles = self._build_resize_handles()
        self.set_busy(False)

    def _build_toolbar(self, layout: QVBoxLayout) -> None:
        toolbar = QHBoxLayout()
        heading = QVBoxLayout()
        heading.setSpacing(4)
        title = QLabel("Tu biblioteca", self)
        title.setObjectName("PageTitle")
        heading.addWidget(title)
        subtitle = QLabel("Canciones, álbumes y sus historias", self)
        subtitle.setObjectName("MutedLabel")
        heading.addWidget(subtitle)
        toolbar.addLayout(heading)
        toolbar.addStretch()
        self.open_button = QPushButton(icon("open"), "Abrir catálogo…", self)
        self.open_button.setObjectName("PrimaryButton")
        self.open_button.setShortcut("Ctrl+O")
        self.open_button.setToolTip("Abrir catálogo SQLite (Ctrl+O)")
        self.open_button.clicked.connect(self.open_requested.emit)
        self.import_action = QAction(icon("import"), "Importar música…", self)
        self.import_action.setShortcut("Ctrl+I")
        self.import_action.triggered.connect(self.import_requested.emit)
        self.addAction(self.import_action)
        self.import_button = QPushButton(icon("import"), "Importar música…", self)
        self.import_button.setToolTip("Importar música y generar el catálogo (Ctrl+I)")
        self.import_button.setAccessibleName("Importar música")
        self.import_button.clicked.connect(self.import_action.trigger)
        self.refresh_button = QPushButton(icon("refresh"), "Actualizar", self)
        self.refresh_button.setShortcut("Ctrl+R")
        self.refresh_button.setToolTip("Actualizar catálogo (Ctrl+R)")
        self.refresh_button.clicked.connect(self.refresh_requested.emit)
        toolbar.addWidget(self.open_button)
        toolbar.addWidget(self.import_button)
        toolbar.addWidget(self.refresh_button)
        layout.addLayout(toolbar)

    def _build_catalog(self) -> QWidget:
        panel = QFrame(self)
        panel.setObjectName("CatalogPanel")
        panel.setMinimumWidth(340)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        header = QWidget(panel)
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(16, 14, 16, 14)
        label = QLabel("CANCIONES", header)
        label.setObjectName("SectionTitle")
        self.count_label = QLabel("0", header)
        self.count_label.setObjectName("CountBadge")
        header_layout.addWidget(label)
        header_layout.addStretch()
        header_layout.addWidget(self.count_label)
        layout.addWidget(header)
        self.model = CatalogTableModel(self)
        self.table = QTableView(panel)
        self.table.setObjectName("CatalogTable")
        self.table.setModel(self.model)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(False)
        self.table.setShowGrid(False)
        self.table.setWordWrap(False)
        self.table.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.table.verticalHeader().hide()
        self.table.verticalHeader().setDefaultSectionSize(48)
        self.table.horizontalHeader().setHighlightSections(False)
        self.table.horizontalHeader().setMinimumSectionSize(45)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.table.horizontalHeader().setStretchLastSection(True)
        for column, width in enumerate((176, 112, 126, 56, 160)):
            self.table.setColumnWidth(column, width)
        self.table.setAccessibleName("Canciones del catálogo")
        self.table.selectionModel().currentRowChanged.connect(self._selection_changed)
        layout.addWidget(self.table, 1)
        self.empty_label = QLabel("Abre un catálogo o importa una carpeta de música.", panel)
        self.empty_label.setObjectName("EmptyCatalog")
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_label.setWordWrap(True)
        self.empty_label.setMinimumHeight(86)
        layout.addWidget(self.empty_label)
        return panel

    def _field(self, key: str, label: str, parent: QWidget) -> QWidget:
        container = QWidget(parent)
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        caption = QLabel(label, container)
        caption.setObjectName("FieldLabel")
        value = QLineEdit(container)
        value.setObjectName("TrackTitle" if key == "title" else "MetadataField")
        value.setReadOnly(True)
        value.setAccessibleName(label)
        value.setMinimumWidth(0)
        value.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        value.installEventFilter(self)
        self.fields[key] = value
        caption.setBuddy(value)
        layout.addWidget(caption)
        layout.addWidget(value)
        value.textEdited.connect(lambda _text, field=key: self._draft_changed(field))
        if key in ("artists", "genres"):
            labels = OrderedLabels(label, container)
            labels.hide()
            labels.changed.connect(lambda field=key: self._draft_changed(field))
            labels.suggestion_requested.connect(
                lambda query, field=key: self.suggestions_requested.emit(field, query)
            )
            self.ordered_labels[key] = labels
            layout.addWidget(labels)
        error = QLabel(container)
        error.setObjectName("FieldError")
        error.setTextFormat(Qt.TextFormat.PlainText)
        error.setWordWrap(True)
        error.hide()
        self.field_errors[key] = error
        layout.addWidget(error)
        return container

    def _build_detail(self) -> QWidget:
        scroll = QScrollArea(self)
        scroll.setObjectName("DetailScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setMinimumWidth(390)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        panel = QFrame(scroll)
        panel.setObjectName("DetailPanel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(22, 20, 22, 22)
        layout.setSpacing(22)
        heading = QHBoxLayout()
        title = QLabel("DETALLE DE LA CANCIÓN", panel)
        title.setObjectName("SectionTitle")
        heading.addWidget(title)
        heading.addStretch()
        self.edit_action = QAction("Editar", self)
        self.edit_action.setShortcut(QKeySequence("Ctrl+E"))
        self.edit_action.triggered.connect(self.edit_requested.emit)
        self.save_action = QAction("Guardar", self)
        self.save_action.setShortcut(QKeySequence(QKeySequence.StandardKey.Save))
        self.save_action.triggered.connect(self.save_requested.emit)
        self.cancel_edit_action = QAction("Cancelar", self)
        self.cancel_edit_action.setShortcut(QKeySequence(Qt.Key.Key_Escape))
        self.cancel_edit_action.triggered.connect(self.cancel_edit_requested.emit)
        self.edit_button = QPushButton("Editar", panel)
        self.save_button = QPushButton("Guardar", panel)
        self.save_button.setObjectName("PrimaryButton")
        self.cancel_edit_button = QPushButton("Cancelar", panel)
        for action, button in (
            (self.edit_action, self.edit_button),
            (self.save_action, self.save_button),
            (self.cancel_edit_action, self.cancel_edit_button),
        ):
            self.addAction(action)
            button.setToolTip(f"{action.text()} ({action.shortcut().toString()})")
            button.clicked.connect(action.trigger)
            heading.addWidget(button)
        layout.addLayout(heading)
        self.edit_status = QLabel(panel)
        self.edit_status.setObjectName("MutedLabel")
        self.edit_status.setTextFormat(Qt.TextFormat.PlainText)
        self.edit_status.setWordWrap(True)
        self.edit_status.hide()
        layout.addWidget(self.edit_status)
        identification = QHBoxLayout()
        identification.setSpacing(18)
        self.cover = CoverLabel(panel)
        identification.addWidget(self.cover)
        names = QVBoxLayout()
        names.setSpacing(14)
        names.addWidget(self._field("title", "CANCIÓN", panel))
        names.addWidget(self._field("artists", "ARTISTA(S)", panel))
        names.addStretch()
        identification.addLayout(names, 1)
        layout.addLayout(identification)

        album = QHBoxLayout()
        album.setSpacing(14)
        album.addWidget(self._field("album", "ÁLBUM", panel), 3)
        album.addWidget(self._field("album_year", "AÑO", panel), 1)
        layout.addLayout(album)
        numbering = QGridLayout()
        numbering.setHorizontalSpacing(12)
        numbering.setVerticalSpacing(14)
        numbering.addWidget(self._field("track_number", "PISTA", panel), 0, 0)
        numbering.addWidget(self._field("track_total", "TOTAL DE PISTAS", panel), 0, 1)
        numbering.addWidget(self._field("disc_number", "DISCO", panel), 0, 2)
        numbering.addWidget(self._field("disc_total", "TOTAL DE DISCOS", panel), 0, 3)
        layout.addLayout(numbering)
        layout.addWidget(self._field("genres", "GÉNERO(S)", panel))
        lyrics_layout = QVBoxLayout()
        lyrics_layout.setSpacing(8)
        lyrics_label = QLabel("LÍRICAS", panel)
        lyrics_label.setObjectName("FieldLabel")
        lyrics_layout.addWidget(lyrics_label)
        self.lyrics = QPlainTextEdit(panel)
        self.lyrics.setObjectName("Lyrics")
        self.lyrics.setReadOnly(True)
        self.lyrics.setAccessibleName("Líricas")
        self.lyrics.setMinimumHeight(140)
        self.lyrics.installEventFilter(self)
        self.lyrics.textChanged.connect(lambda: self._draft_changed("lyrics"))
        lyrics_label.setBuddy(self.lyrics)
        lyrics_layout.addWidget(self.lyrics, 1)
        lyrics_error = QLabel(panel)
        lyrics_error.setObjectName("FieldError")
        lyrics_error.setTextFormat(Qt.TextFormat.PlainText)
        lyrics_error.setWordWrap(True)
        lyrics_error.hide()
        self.field_errors["lyrics"] = lyrics_error
        lyrics_layout.addWidget(lyrics_error)
        layout.addLayout(lyrics_layout, 1)
        scroll.setWidget(panel)
        return scroll

    def _build_resize_handles(self) -> list[ResizeHandle]:
        edges = Qt.Edge
        cursors = Qt.CursorShape
        specs = (
            (edges.TopEdge, cursors.SizeVerCursor),
            (edges.BottomEdge, cursors.SizeVerCursor),
            (edges.LeftEdge, cursors.SizeHorCursor),
            (edges.RightEdge, cursors.SizeHorCursor),
            (edges.TopEdge | edges.LeftEdge, cursors.SizeFDiagCursor),
            (edges.TopEdge | edges.RightEdge, cursors.SizeBDiagCursor),
            (edges.BottomEdge | edges.LeftEdge, cursors.SizeBDiagCursor),
            (edges.BottomEdge | edges.RightEdge, cursors.SizeFDiagCursor),
        )
        return [ResizeHandle(self, edge, cursor) for edge, cursor in specs]

    def _place_resize_handles(self) -> None:
        if not hasattr(self, "_handles"):
            return
        width, height = self.width(), self.height()
        geometries = (
            QRect(14, 0, width - 28, 6),
            QRect(14, height - 6, width - 28, 6),
            QRect(0, 14, 6, height - 28),
            QRect(width - 6, 14, 6, height - 28),
            QRect(0, 0, 14, 14),
            QRect(width - 14, 0, 14, 14),
            QRect(0, height - 14, 14, 14),
            QRect(width - 14, height - 14, 14, 14),
        )
        for handle, geometry in zip(self._handles, geometries, strict=True):
            handle.setGeometry(geometry)
            handle.setVisible(not self.isMaximized() and not self._system_frame)
            handle.raise_()

    def needs_system_frame(self) -> bool:
        return QGuiApplication.platformName().startswith("wayland")

    def use_system_frame(self) -> None:
        """Keep window controls available if a compositor refuses Qt move/resize."""
        self._system_frame = True
        self.title_bar.hide()
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint, False)
        self.show()
        self._place_resize_handles()
        self.set_status("Marco del sistema activado para mover y redimensionar la ventana.")

    def toggle_maximized(self) -> None:
        self.showNormal() if self.isMaximized() else self.showMaximized()

    def set_catalog(
        self,
        path: Path | None,
        rows: tuple[CatalogSummary, ...],
        selected_file_id: int | None = None,
    ) -> None:
        preferred = selected_file_id
        if preferred is None and path == self._catalog_path:
            preferred = self._current_file_id
        self._catalog_path = path
        blocker = QSignalBlocker(self.table.selectionModel())
        self.model.set_summaries(rows)
        self.table.clearSelection()
        row = self.model.row_for_file(preferred)
        if row is None and rows:
            row = 0
        self._current_file_id = self.model.file_id_at(row) if row is not None else None
        if row is not None:
            self.table.selectRow(row)
        del blocker
        self.set_detail(None)
        self.count_label.setText(str(len(rows)))
        self.empty_label.setVisible(not rows)
        self.empty_label.setText(
            "Este catálogo todavía no contiene canciones."
            if path is not None
            else "Abre un catálogo o importa una carpeta de música."
        )
        self.catalog_label.setText(path.name if path is not None else "Sin catálogo")
        self.catalog_label.setToolTip(str(path) if path is not None else "")
        self.set_busy(self._busy)
        if self._current_file_id is not None:
            self.track_selected.emit(self._current_file_id)

    def _selection_changed(self, current: QModelIndex, previous: QModelIndex) -> None:
        if self._importing or self._saving:
            return
        file_id = self.model.file_id_at(current.row()) if current.isValid() else None
        if file_id == self._current_file_id:
            return
        if (
            file_id is not None
            and self.selection_guard is not None
            and not self.selection_guard(file_id)
        ):
            self._restore_selection()
            return
        self._current_file_id = file_id
        self.set_detail(None)
        if file_id is not None:
            self.track_selected.emit(file_id)

    def current_file_id(self) -> int | None:
        return self._current_file_id

    def _restore_selection(self) -> None:
        blocker = QSignalBlocker(self.table.selectionModel())
        row = self.model.row_for_file(self._current_file_id)
        if row is None:
            self.table.clearSelection()
            self.table.setCurrentIndex(QModelIndex())
        else:
            self.table.selectRow(row)
        del blocker

    def select_file(self, file_id: int) -> None:
        """Continue a selection that the controller deferred while saving a draft."""
        row = self.model.row_for_file(file_id)
        if row is not None:
            self.table.selectRow(row)

    def set_detail(self, entry: CatalogEntry | None) -> None:
        # Results from a query started before editing must never overwrite the draft.
        if self._editing:
            return
        self._detail_loaded = entry is not None
        for field in self.fields.values():
            field.clear()
        self.lyrics.clear()
        self.cover.set_cover(None)
        self._update_actions()
        if entry is None:
            return
        data = entry.metadata
        values = {
            "title": data.title,
            "artists": "; ".join(data.artists),
            "album": data.album,
            "album_year": data.album_year,
            "track_number": data.track_number,
            "track_total": data.track_total,
            "disc_number": data.disc_number,
            "disc_total": data.disc_total,
            "genres": "; ".join(data.genres),
        }
        for key, value in values.items():
            self.fields[key].setText(str(value) if value is not None else "")
            self.fields[key].setCursorPosition(0)
        self.lyrics.setPlainText(data.lyrics or "")
        self.cover.set_cover(data.artwork.data if data.artwork is not None else None)

    def set_edit_enabled(self, enabled: bool) -> None:
        """Expose editing only when the composition root supplies the edit adapter."""
        self._edit_enabled = enabled
        self._update_actions()

    def begin_edit(self, values: EditableValues) -> None:
        self._updating_edit = True
        self._edit_values = values
        self._editing = True
        self._saving = False
        for key, field in self.fields.items():
            value = getattr(values, key)
            field.setText(
                "; ".join(value)
                if isinstance(value, tuple)
                else str(value)
                if value is not None
                else ""
            )
            field.setCursorPosition(0)
        self.ordered_labels["artists"].set_names(values.artists)
        self.ordered_labels["genres"].set_names(values.genres)
        self.lyrics.setPlainText(values.lyrics or "")
        self._updating_edit = False
        self.set_field_errors({})
        self._dirty = False
        self.dirty_changed.emit(False)
        self._validate_draft()
        self._update_actions()
        self.fields["title"].setFocus()

    def edit_patch(self) -> TrackEditPatch:
        """Collect only differences; the application validates the raw number strings."""
        if self._edit_values is None:
            return TrackEditPatch(())
        changes = []
        for key, field in self.fields.items():
            original = getattr(self._edit_values, key)
            if key in self.ordered_labels:
                value: str | int | tuple[str, ...] | None = self.ordered_labels[key].names()
            else:
                text = field.text()
                if key in ("title", "album"):
                    if text == (original or ""):
                        continue
                    value = text if text.strip() else None
                elif (
                    len(text.strip()) <= 19 and text.strip().isascii() and text.strip().isdecimal()
                ):
                    value = int(text.strip())
                else:
                    value = text.strip() or None
            if value != original:
                changes.append(FieldChange(cast(EditField, key), value))
        lyrics = self.lyrics.toPlainText() or None
        if lyrics != self._edit_values.lyrics:
            changes.append(FieldChange("lyrics", lyrics))
        return TrackEditPatch(tuple(changes))

    def edit_dirty(self) -> bool:
        return self._editing and bool(self.edit_patch().changes)

    def set_edit_state(self, editing: bool, saving: bool = False) -> None:
        self._editing = editing
        self._saving = saving
        if not editing:
            self._edit_values = None
            self._dirty = False
            self._edit_valid = True
            self.set_field_errors({})
            self.dirty_changed.emit(False)
        self._update_actions()

    def set_field_errors(self, errors: dict[str, str]) -> None:
        for key, label in self.field_errors.items():
            message = errors.get(key, "")
            label.setText(message)
            label.setVisible(bool(message))
        self._edit_valid = not errors
        self._update_actions()

    def set_suggestions(self, field: str, names: tuple[str, ...]) -> None:
        """Apply already-filtered asynchronous suggestions to the active name control."""
        if self._editing and not self._saving and field in self.ordered_labels:
            self.ordered_labels[field].set_suggestions(names)

    def _draft_changed(self, field: str) -> None:
        if not self._editing or self._updating_edit or self._saving:
            return
        self._validate_draft()
        dirty = self.edit_dirty()
        if dirty != self._dirty:
            self._dirty = dirty
            self.dirty_changed.emit(dirty)
        self._update_actions()

    def _validate_draft(self) -> None:
        from trackfolio.application.edit_catalog import (
            CatalogEditValidationError,
            validate_edit_patch,
        )

        if self._edit_values is None:
            return
        try:
            validate_edit_patch(self._edit_values, self.edit_patch())
        except CatalogEditValidationError as error:
            self.set_field_errors({issue.field: issue.message for issue in error.errors})
        else:
            self.set_field_errors({})

    def set_status(self, text: str) -> None:
        self.status_label.setText(text)

    def set_error(self, message: str) -> None:
        self.error_label.setText(message)
        self.error_label.setVisible(bool(message))

    def set_busy(self, busy: bool) -> None:
        self._busy = busy
        self._update_actions()

    def set_importing(self, importing: bool) -> None:
        """Keep import ownership separate from asynchronous read-query activity."""
        self._importing = importing
        self._update_actions()

    def _update_actions(self) -> None:
        navigating = not self._importing and not self._saving
        self.open_button.setEnabled(navigating)
        self.import_button.setEnabled(navigating)
        self.import_action.setEnabled(navigating)
        self.refresh_button.setEnabled(
            self._catalog_path is not None and not self._busy and navigating
        )
        self.table.setEnabled(navigating)
        self.edit_action.setEnabled(
            self._edit_enabled
            and self._detail_loaded
            and not self._busy
            and navigating
            and not self._editing
        )
        self.save_action.setEnabled(
            self._editing and not self._saving and self._edit_valid and self.edit_dirty()
        )
        self.cancel_edit_action.setEnabled(self._editing and not self._saving)
        for action, button in (
            (self.edit_action, self.edit_button),
            (self.save_action, self.save_button),
            (self.cancel_edit_action, self.cancel_edit_button),
        ):
            button.setEnabled(action.isEnabled())
        self.edit_button.setVisible(not self._editing)
        self.save_button.setVisible(self._editing)
        self.cancel_edit_button.setVisible(self._editing)
        for key, field in self.fields.items():
            field.setReadOnly(not self._editing or key in self.ordered_labels)
            field.setEnabled(not self._saving)
            if key in self.ordered_labels:
                field.setVisible(not self._editing)
                labels = self.ordered_labels[key]
                labels.setVisible(self._editing)
                labels.setEnabled(not self._saving)
        self.lyrics.setReadOnly(not self._editing)
        self.lyrics.setEnabled(not self._saving)
        self.edit_status.setVisible(self._editing)
        self.edit_status.setText(
            "Guardando cambios…"
            if self._saving
            else "Cambios en el catálogo · Cambios sin guardar"
            if self.edit_dirty()
            else "Cambios en el catálogo"
        )

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._place_resize_handles()

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        # QLineEdit otherwise reserves Ctrl+E for End-of-Line on Unix, even readonly.
        if event.type() == QEvent.Type.ShortcutOverride and hasattr(self, "edit_action"):
            key_event = cast(QKeyEvent, event)
            if (
                self.edit_action.isEnabled()
                and key_event.key() == Qt.Key.Key_E
                and key_event.modifiers() == Qt.KeyboardModifier.ControlModifier
            ):
                event.ignore()
                return True
        return super().eventFilter(watched, event)

    def changeEvent(self, event: QEvent) -> None:
        super().changeEvent(event)
        if event.type() == QEvent.Type.WindowStateChange and hasattr(self, "title_bar"):
            self.title_bar.sync_window_state()
            self._place_resize_handles()

    def closeEvent(self, event: QCloseEvent) -> None:
        if self.close_guard is not None and not self.close_guard():
            event.ignore()
            return
        self.closing.emit()
        event.accept()
