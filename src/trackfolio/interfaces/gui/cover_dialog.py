"""Resolve ambiguous sidecar images once per folder, on the GUI thread."""

from __future__ import annotations

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QSize, Qt
from PySide6.QtGui import QImageReader, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from trackfolio.domain.tag_write import CoverChoice, CoverDiscovery, CoverFolder
from trackfolio.infrastructure.cover_files import FileCoverAccess
from trackfolio.interfaces.gui.theme import icon


class CoverChoiceDialog(QDialog):
    def __init__(self, discovery: CoverDiscovery, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Choose covers")
        self.setModal(True)
        self.resize(780, 560)
        self.setMinimumSize(660, 460)
        self.rows: list[tuple[CoverFolder, QListWidget, QLabel]] = []
        self._captions: list[QLabel] = []
        self._valid: dict[int, bool] = {}
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 16)
        layout.setSpacing(16)
        title = QLabel("Choose a cover", self)
        title.setProperty("role", "primary")
        font = title.font()
        font.setPointSize(16)
        title.setFont(font)
        layout.addWidget(title)
        heading = QLabel("Select an image per folder or keep the current cover.")
        heading.setProperty("role", "secondary")
        heading.setWordWrap(True)
        layout.addWidget(heading)
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        content = QWidget(scroll)
        folders = QVBoxLayout(content)
        folders.setContentsMargins(0, 0, 0, 0)
        folders.setSpacing(16)
        folders.setAlignment(Qt.AlignmentFlag.AlignTop)
        for folder in discovery.folders:
            if len(folder.candidates) <= 1:
                continue
            card = QFrame(content)
            card.setObjectName("CatalogPanel")
            card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
            panel = QVBoxLayout(card)
            panel.setContentsMargins(16, 16, 16, 16)
            panel.setSpacing(12)
            name = QLabel(folder.path.name, card)
            name.setProperty("role", "primary")
            name.setWordWrap(True)
            panel.addWidget(name)
            path = QLabel(str(folder.path), card)
            path.setProperty("role", "secondary")
            path.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            path.setWordWrap(True)
            panel.addWidget(path)
            body = QHBoxLayout()
            body.setSpacing(18)
            images = QVBoxLayout()
            images.setSpacing(8)
            label = QLabel(f"AVAILABLE IMAGES · {len(folder.candidates)}", card)
            label.setObjectName("SectionTitle")
            images.addWidget(label)
            candidates = QListWidget(card)
            candidates.setAccessibleName(f"Cover for {folder.path}")
            candidates.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
            candidates.setMinimumHeight(260)
            preserve = QListWidgetItem("Keep current cover\nLeave the embedded image unchanged")
            preserve.setSizeHint(QSize(0, 56))
            candidates.addItem(preserve)
            for candidate in folder.candidates:
                detail = (
                    "Unavailable"
                    if candidate.error
                    else f"{candidate.width} × {candidate.height} px"
                )
                item = QListWidgetItem(f"{candidate.path.name}\n{detail}")
                item.setToolTip(candidate.error or candidate.path.name)
                item.setSizeHint(QSize(0, 56))
                candidates.addItem(item)
            images.addWidget(candidates, 1)
            body.addLayout(images, 1)
            display = QVBoxLayout()
            display.setSpacing(8)
            label = QLabel("PREVIEW", card)
            label.setObjectName("SectionTitle")
            display.addWidget(label)
            preview = QLabel("Select an image\nto preview the cover", card)
            preview.setObjectName("Cover")
            preview.setFixedSize(260, 260)
            preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
            preview.setWordWrap(True)
            display.addWidget(preview)
            caption = QLabel("", card)
            caption.setProperty("role", "secondary")
            caption.setFixedWidth(260)
            caption.setWordWrap(True)
            display.addWidget(caption)
            display.addStretch()
            body.addLayout(display)
            panel.addLayout(body)
            folders.addWidget(card)
            index = len(self.rows)
            self.rows.append((folder, candidates, preview))
            self._captions.append(caption)
            self._valid[index] = False
            candidates.currentRowChanged.connect(lambda _value, row=index: self._update(row))
        scroll.setWidget(content)
        layout.addWidget(scroll, 1)
        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel, self
        )
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setIcon(icon("check"))
        self.buttons.button(QDialogButtonBox.StandardButton.Cancel).setIcon(icon("close"))
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Use selection")
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setObjectName("PrimaryButton")
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(False)
        layout.addWidget(self.buttons)

    def _update(self, index: int) -> None:
        folder, candidates, preview = self.rows[index]
        selected = candidates.currentRow()
        preview.clear()
        self._captions[index].clear()
        valid = selected == 0
        if selected == 0:
            preview.setText("The current cover\nwill be preserved")
        elif selected > 0:
            candidate = folder.candidates[selected - 1]
            self._captions[index].setText(candidate.path.name)
            if candidate.error:
                preview.setText(candidate.error)
            else:
                try:
                    image = FileCoverAccess().read(folder.library_root, candidate, lambda: False)
                except Exception as exc:
                    preview.setText(str(exc))
                    self._valid[index] = False
                    self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(False)
                    return
                buffer = QBuffer(self)
                buffer.setData(QByteArray(image.data or b""))
                buffer.open(QIODevice.OpenModeFlag.ReadOnly)
                reader = QImageReader(buffer)
                reader.setAutoTransform(True)
                reader.setScaledSize(
                    reader.size().scaled(244, 244, Qt.AspectRatioMode.KeepAspectRatio)
                )
                picture = reader.read()
                buffer.close()
                buffer.deleteLater()
                valid = not picture.isNull()
                if valid:
                    preview.setPixmap(QPixmap.fromImage(picture))
                else:
                    preview.setText("Cannot decode this image. Choose another or keep the cover.")
        else:
            preview.setText("Select an image\nto preview the cover")
        self._valid[index] = valid
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(
            all(self._valid.values())
        )

    def choices(self) -> tuple[CoverChoice, ...]:
        return tuple(
            CoverChoice(
                folder.path,
                None
                if candidates.currentRow() == 0
                else folder.candidates[candidates.currentRow() - 1].path,
            )
            for folder, candidates, _ in self.rows
        )
