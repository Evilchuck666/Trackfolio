"""Browse artists and open their album editions in the album view."""

from PySide6.QtCore import QSignalBlocker, Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from trackfolio.application.artists import group_artists
from trackfolio.domain.album import Album


class ArtistView(QWidget):
    album_requested = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._groups: dict[str | None, tuple[Album, ...]] = {}
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 12, 0, 0)
        split = QSplitter(self)
        split.setHandleWidth(14)
        layout.addWidget(split)
        navigation = QFrame(split)
        navigation.setObjectName("CatalogPanel")
        left = QVBoxLayout(navigation)
        heading = QLabel("ARTISTAS", navigation)
        heading.setObjectName("SectionTitle")
        left.addWidget(heading)
        self.search = QLineEdit(navigation)
        self.search.setPlaceholderText("Buscar artista…")
        self.search.setAccessibleName("Buscar artistas")
        left.addWidget(self.search)
        self.list = QListWidget(navigation)
        self.list.setAccessibleName("Artistas del catálogo")
        left.addWidget(self.list)
        self.count = QLabel(navigation)
        self.count.setProperty("role", "secondary")
        left.addWidget(self.count)
        panel = QFrame(split)
        panel.setObjectName("DetailPanel")
        right = QVBoxLayout(panel)
        right.setContentsMargins(22, 22, 22, 22)
        right.setSpacing(16)
        self.title = QLabel(panel)
        self.title.setObjectName("songTitle")
        self.title.setTextFormat(Qt.TextFormat.PlainText)
        self.title.setWordWrap(True)
        right.addWidget(self.title)
        self.summary = QLabel(panel)
        self.summary.setProperty("role", "secondary")
        self.summary.setWordWrap(True)
        right.addWidget(self.summary)
        self.albums = QListWidget(panel)
        self.albums.setAccessibleName("Álbumes del artista")
        right.addWidget(self.albums, 1)
        self.open_button = QPushButton("Ver álbum", panel)
        right.addWidget(self.open_button, 0, Qt.AlignmentFlag.AlignLeft)
        split.setSizes([300, 900])
        self.search.textChanged.connect(self._filter)
        self.list.currentRowChanged.connect(self._selected)
        self.albums.currentRowChanged.connect(self._actions)
        self.albums.itemActivated.connect(lambda _: self._open())
        self.open_button.clicked.connect(self._open)
        self.set_albums(())

    def set_albums(self, albums: tuple[Album, ...]) -> None:
        previous = self.list.currentItem()
        name = previous.data(Qt.ItemDataRole.UserRole) if previous else None
        self._groups = group_artists(albums)
        blocker = QSignalBlocker(self.list)
        self.list.clear()
        selected = 0
        for row, (artist, editions) in enumerate(self._groups.items()):
            item = QListWidgetItem(artist if artist is not None else "Sin artista de álbum")
            item.setData(Qt.ItemDataRole.UserRole, artist)
            item.setToolTip(f"{len(editions)} álbumes")
            self.list.addItem(item)
            if previous is not None and artist == name:
                selected = row
        self.list.setCurrentRow(selected)
        del blocker
        count = sum(name is not None for name in self._groups)
        self.count.setText(f"{count} " + ("artista" if count == 1 else "artistas"))
        self._filter(self.search.text())

    def _filter(self, query: str) -> None:
        visible = []
        for row in range(self.list.count()):
            item = self.list.item(row)
            item.setHidden(query.casefold() not in item.text().casefold())
            if not item.isHidden():
                visible.append(row)
        current = self.list.currentRow()
        self.list.setCurrentRow(current if current in visible else visible[0] if visible else -1)
        self._selected()

    def _selected(self) -> None:
        self.albums.clear()
        item = self.list.currentItem()
        if item is None:
            self.title.setText("Sin artistas")
            self.summary.setText(
                "No hay artistas que coincidan con la búsqueda."
                if self._groups
                else "Abre un catálogo o importa música para ver tus artistas."
            )
            self._actions()
            return
        editions = self._groups[item.data(Qt.ItemDataRole.UserRole)]
        self.title.setText(item.text())
        self.summary.setText(
            f"{len(editions)} álbumes · {sum(len(a.tracks) for a in editions)} pistas"
        )
        for album in editions:
            row = QListWidgetItem(
                f"{album.year or 'Sin año'} · {album.title or 'Sin álbum'}\n"
                f"{len(album.tracks)} pistas · {album.directory}"
            )
            row.setData(Qt.ItemDataRole.UserRole, album.key)
            row.setToolTip(str(album.library_root / album.directory))
            self.albums.addItem(row)
        self.albums.setCurrentRow(0)
        self._actions()

    def _actions(self) -> None:
        self.open_button.setEnabled(self.albums.currentItem() is not None)

    def _open(self) -> None:
        item = self.albums.currentItem()
        if item is not None:
            self.album_requested.emit(item.data(Qt.ItemDataRole.UserRole))
