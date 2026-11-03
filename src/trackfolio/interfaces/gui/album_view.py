"""Album navigation, edition details and an explicit editor for common fields."""

from __future__ import annotations

from collections.abc import Callable
from typing import cast

from PySide6.QtCore import QSignalBlocker, Qt, Signal
from PySide6.QtGui import QIntValidator
from PySide6.QtWidgets import (
    QCheckBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QScrollArea,
    QSplitter,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from trackfolio.domain.album import Album
from trackfolio.domain.catalog_edit import EditableTrack, EditField, FieldChange, TrackEditPatch
from trackfolio.interfaces.gui.cover_widget import CoverLabel
from trackfolio.interfaces.gui.ordered_labels import OrderedLabels


class AlbumView(QWidget):
    draft_changed = Signal()
    album_selected = Signal(object)
    edit_requested = Signal()
    save_requested = Signal()
    cancel_requested = Signal()
    write_requested = Signal()
    track_requested = Signal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.selection_guard: Callable[[str], bool] | None = None
        self._albums: dict[str, Album] = {}
        self.current_album: Album | None = None
        self._editing = False
        self._busy = False
        self._blocked = False
        self.edit_enabled = False
        self.write_enabled = False
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 12, 0, 0)
        split = QSplitter(self)
        split.setHandleWidth(14)
        layout.addWidget(split)
        navigation = QFrame(split)
        navigation.setObjectName("CatalogPanel")
        left = QVBoxLayout(navigation)
        heading = QLabel("ÁLBUMES", navigation)
        heading.setObjectName("SectionTitle")
        left.addWidget(heading)
        self.search = QLineEdit(navigation)
        self.search.setPlaceholderText("Buscar álbum o artista…")
        self.search.setAccessibleName("Buscar álbumes")
        self.search.textChanged.connect(self._filter)
        left.addWidget(self.search)
        self.list = QListWidget(navigation)
        self.list.setAccessibleName("Álbumes del catálogo")
        self.list.currentRowChanged.connect(self._selected)
        left.addWidget(self.list)
        self.count = QLabel("Sin álbumes", navigation)
        self.count.setProperty("role", "secondary")
        left.addWidget(self.count)
        self.pages = QStackedWidget(split)
        empty = QLabel("Abre un catálogo o importa música para ver tus álbumes.", self)
        self.empty_label = empty
        empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty.setWordWrap(True)
        self.pages.addWidget(empty)
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        panel = QFrame(scroll)
        panel.setObjectName("DetailPanel")
        right = QVBoxLayout(panel)
        right.setContentsMargins(22, 22, 22, 22)
        right.setSpacing(16)
        header = QHBoxLayout()
        self.cover = CoverLabel(panel)
        header.addWidget(self.cover, 0, Qt.AlignmentFlag.AlignTop)
        info = QVBoxLayout()
        self.title = QLabel(panel)
        self.title.setObjectName("songTitle")
        self.title.setWordWrap(True)
        self.artists = QLabel(panel)
        self.artists.setWordWrap(True)
        self.stats = QLabel(panel)
        self.stats.setProperty("role", "secondary")
        self.stats.setWordWrap(True)
        self.genres = QLabel(panel)
        self.genres.setWordWrap(True)
        self.path = QLabel(panel)
        self.path.setProperty("role", "secondary")
        self.path.setWordWrap(True)
        self.path.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        for label in (self.title, self.artists, self.stats, self.genres, self.path):
            label.setTextFormat(Qt.TextFormat.PlainText)
            info.addWidget(label)
        info.addStretch()
        header.addLayout(info, 1)
        right.addLayout(header)
        actions = QHBoxLayout()
        self.edit_button = QPushButton("Editar álbum", panel)
        self.edit_button.clicked.connect(self.edit_requested.emit)
        self.write_button = QPushButton("Escribir etiquetas del álbum…", panel)
        self.write_button.clicked.connect(self.write_requested.emit)
        self.save_button = QPushButton("Guardar álbum", panel)
        self.save_button.setObjectName("PrimaryButton")
        self.save_button.clicked.connect(self.save_requested.emit)
        self.cancel_button = QPushButton("Cancelar", panel)
        self.cancel_button.clicked.connect(self.cancel_requested.emit)
        for button in (self.edit_button, self.write_button, self.save_button, self.cancel_button):
            actions.addWidget(button)
        actions.addStretch()
        right.addLayout(actions)
        self.editor = QWidget(panel)
        form = QGridLayout(self.editor)
        form.setContentsMargins(0, 0, 0, 0)
        note = QLabel(
            "Marca los datos que quieras aplicar a todas las pistas. "
            "Los artistas de cada canción se conservarán.",
            self.editor,
        )
        note.setWordWrap(True)
        note.setProperty("role", "secondary")
        form.addWidget(note, 0, 0, 1, 2)
        self.fields = {"album": QLineEdit(self.editor), "album_year": QLineEdit(self.editor)}
        self.fields["album_year"].setValidator(QIntValidator(1, 9999, self.editor))
        self.labels = {
            "album_artists": OrderedLabels("Artistas del álbum", self.editor),
            "genres": OrderedLabels("Géneros", self.editor),
        }
        self.apply_fields: dict[str, QCheckBox] = {}
        for row, (field, caption) in enumerate(
            (
                ("album", "Álbum"),
                ("album_year", "Año"),
                ("album_artists", "Artistas del álbum"),
                ("genres", "Géneros"),
            ),
            1,
        ):
            check = QCheckBox(caption, self.editor)
            check.setToolTip("Aplicar a todas las pistas. Un valor vacío elimina el campo.")
            control = self.fields[field] if field in self.fields else self.labels[field]
            control.setAccessibleName(caption)
            check.toggled.connect(control.setEnabled)
            check.toggled.connect(self._draft_changed)
            self.apply_fields[field] = check
            form.addWidget(check, row, 0, Qt.AlignmentFlag.AlignTop)
            form.addWidget(control, row, 1)
        for field_control in self.fields.values():
            field_control.textChanged.connect(self._draft_changed)
        for ordered in self.labels.values():
            ordered.changed.connect(self._draft_changed)
        self.error = QLabel(self.editor)
        self.error.setObjectName("FieldError")
        self.error.setWordWrap(True)
        form.addWidget(self.error, 5, 0, 1, 2)
        right.addWidget(self.editor)
        self.table = QTableWidget(0, 5, panel)
        self.table.setHorizontalHeaderLabels(
            ("Disco", "Pista", "Canción", "Artista(s)", "Duración")
        )
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.verticalHeader().hide()
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.table.setMinimumHeight(230)
        self.table.setAccessibleName("Pistas del álbum")
        self.table.verticalHeader().setDefaultSectionSize(40)
        self.table.cellDoubleClicked.connect(self._open_track)
        right.addWidget(self.table, 1)
        scroll.setWidget(panel)
        self.pages.addWidget(scroll)
        split.setStretchFactor(0, 1)
        split.setStretchFactor(1, 3)
        split.setSizes([300, 900])
        self.set_editing(False)

    def set_albums(self, albums: tuple[Album, ...]) -> None:
        previous = self.current_album
        selected = next(
            (a.key for a in albums if previous and set(a.file_ids) & set(previous.file_ids)), None
        )
        self._albums = {album.key: album for album in albums}
        blocker = QSignalBlocker(self.list)
        self.list.clear()
        self.current_album = None
        selected_row = 0
        for row, album in enumerate(albums):
            artist = " · ".join(album.artists) or "Sin artistas de álbum"
            item = QListWidgetItem(
                f"{album.title or 'Sin álbum'}\n{artist}\n"
                f"{album.year or 'Sin año'} · {len(album.tracks)} pistas"
            )
            item.setData(Qt.ItemDataRole.UserRole, album.key)
            item.setToolTip(str(album.library_root / album.directory))
            self.list.addItem(item)
            if album.key == selected:
                selected_row = row
        self.list.setCurrentRow(-1)
        del blocker
        self.count.setText(f"{len(albums)} " + ("álbum" if len(albums) == 1 else "álbumes"))
        self._filter(self.search.text(), select=False)
        visible = [row for row in range(self.list.count()) if not self.list.item(row).isHidden()]
        if visible:
            self.list.setCurrentRow(selected_row if selected_row in visible else visible[0])
        else:
            self._show_empty()
        self._actions()

    def _show_empty(self) -> None:
        self.current_album = None
        self.album_selected.emit(None)
        self.pages.setCurrentIndex(0)
        self.empty_label.setText(
            "No hay álbumes que coincidan con la búsqueda."
            if self._albums
            else "Abre un catálogo o importa música para ver tus álbumes."
        )

    def _filter(self, query: str, *, select: bool = True) -> None:
        visible = []
        for row in range(self.list.count()):
            item = self.list.item(row)
            if item is not None:
                item.setHidden(query.casefold() not in item.text().casefold())
                if not item.isHidden():
                    visible.append(row)
        if not select:
            return
        current = self.list.currentItem()
        if current is not None and not current.isHidden():
            return
        if visible:
            self.list.setCurrentRow(visible[0])
        else:
            self.list.setCurrentRow(-1)
            self._show_empty()
            self._actions()

    def select_key(self, key: str) -> None:
        for row in range(self.list.count()):
            if self.list.item(row).data(Qt.ItemDataRole.UserRole) == key:
                self.list.setCurrentRow(row)
                return

    def _selected(self, row: int) -> None:
        item = self.list.item(row)
        if item is None:
            return
        key = str(item.data(Qt.ItemDataRole.UserRole))
        previous = self.current_album
        if self.selection_guard is not None and not self.selection_guard(key):
            blocker = QSignalBlocker(self.list)
            if previous is not None:
                self.select_key(previous.key)
            del blocker
            return
        self.current_album = self._albums[key]
        self.show_album(self.current_album)
        self.album_selected.emit(self.current_album)

    def show_album(self, album: Album) -> None:
        self.pages.setCurrentIndex(1)
        self.title.setText(album.title or "Sin álbum")
        self.artists.setText(" · ".join(album.artists) or "Sin artistas de álbum")
        duration = sum(track.duration_seconds or 0 for track in album.tracks)
        discs = len({track.disc_number or 1 for track in album.tracks})
        duration_label = (
            f"{int(duration // 60)} min"
            if all(track.duration_seconds is not None for track in album.tracks)
            else "Duración incompleta"
        )
        discs_label = f"{discs} " + ("disco" if discs == 1 else "discos")
        self.stats.setText(
            f"{album.year or 'Sin año'} · {len(album.tracks)} pistas · "
            f"{discs_label} · {duration_label}"
        )
        self.path.setText(str(album.library_root / album.directory))
        self.genres.setText(f"Géneros: {', '.join(album.genres)}" if album.genres else "")
        self.genres.setVisible(bool(album.genres))
        self.cover.set_cover(None)
        self.table.setRowCount(len(album.tracks))
        for row, track in enumerate(album.tracks):
            seconds = track.duration_seconds
            values = (
                str(track.disc_number) if track.disc_number else "",
                str(track.track_number) if track.track_number else "",
                track.summary.title or "",
                "; ".join(track.summary.artists),
                f"{int(seconds) // 60}:{int(seconds) % 60:02}" if seconds is not None else "",
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setToolTip(track.summary.relative_path)
                self.table.setItem(row, column, item)
        self._actions()

    def begin_edit(self, originals: tuple[EditableTrack, ...]) -> None:
        for field, check in self.apply_fields.items():
            values = [getattr(track.values, field) for track in originals]
            mixed = any(value != values[0] for value in values[1:])
            check.setChecked(False)
            if field in self.fields:
                control = self.fields[field]
                control.setText("" if mixed or values[0] is None else str(values[0]))
                control.setPlaceholderText("Valores distintos" if mixed else "")
                control.setEnabled(False)
            else:
                self.labels[field].set_names(() if mixed else values[0])
                self.labels[field].name_edit.setPlaceholderText(
                    "Valores distintos" if mixed else "Nombre completo"
                )
                self.labels[field].setEnabled(False)
        self.error.clear()
        self.set_editing(True)

    def patch(self) -> TrackEditPatch:
        changes = []
        for field, check in self.apply_fields.items():
            if not check.isChecked():
                continue
            value = (
                self.labels[field].names() if field in self.labels else self.fields[field].text()
            )
            changes.append(FieldChange(cast(EditField, field), value))
        return TrackEditPatch(tuple(changes))

    def _draft_changed(self) -> None:
        if self._editing:
            self._actions()
            self.draft_changed.emit()

    def dirty(self) -> bool:
        return self._editing and not self.patch().empty

    def set_editing(self, editing: bool) -> None:
        self._editing = editing
        self.editor.setVisible(editing)
        self._actions()

    def set_busy(self, busy: bool, *, blocked: bool = False) -> None:
        self._busy = busy
        self._blocked = blocked
        self._actions()

    def _actions(self) -> None:
        self.list.setEnabled(not self._blocked)
        self.search.setEnabled(not self._blocked and not self._editing)
        self.edit_button.setVisible(not self._editing)
        self.save_button.setVisible(self._editing)
        self.cancel_button.setVisible(self._editing)
        self.edit_button.setEnabled(
            self.edit_enabled and self.current_album is not None and not self._busy
        )
        self.write_button.setEnabled(
            self.write_enabled and self.current_album is not None and not self._busy
        )
        self.save_button.setEnabled(not self._busy and self.dirty())
        self.cancel_button.setEnabled(not self._busy)
        self.editor.setEnabled(not self._busy)
        self.table.setEnabled(not self._blocked)

    def _open_track(self, row: int, _column: int) -> None:
        if self.current_album is not None:
            self.track_requested.emit(self.current_album.tracks[row].summary.file_id)
