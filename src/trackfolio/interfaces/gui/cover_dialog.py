"""Resolve ambiguous sidecar images once per folder, on the GUI thread."""

from __future__ import annotations

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, Qt
from PySide6.QtGui import QImageReader, QPixmap
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from trackfolio.domain.tag_write import CoverChoice, CoverDiscovery, CoverFolder
from trackfolio.infrastructure.cover_files import FileCoverAccess


class CoverChoiceDialog(QDialog):
    def __init__(self, discovery: CoverDiscovery, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Elegir portadas")
        self.setModal(True)
        self.resize(640, 550)
        self.rows: list[tuple[CoverFolder, QComboBox, QLabel]] = []
        self._valid: dict[int, bool] = {}
        layout = QVBoxLayout(self)
        heading = QLabel(
            "Hay varias imágenes. Elige una portada para cada carpeta o conserva la actual."
        )
        heading.setWordWrap(True)
        layout.addWidget(heading)
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        content = QWidget(scroll)
        folders = QVBoxLayout(content)
        for folder in discovery.folders:
            if len(folder.candidates) <= 1:
                continue
            label = QLabel(str(folder.path), content)
            label.setWordWrap(True)
            folders.addWidget(label)
            form = QFormLayout()
            combo = QComboBox(content)
            combo.setAccessibleName(f"Portada de {folder.path}")
            combo.addItem("Selecciona una imagen…")
            combo.addItem("Conservar portada actual")
            for candidate in folder.candidates:
                suffix = f" · {candidate.width}×{candidate.height}"
                combo.addItem(
                    candidate.path.name + (" · No disponible" if candidate.error else suffix)
                )
            preview = QLabel(content)
            preview.setMinimumHeight(100)
            preview.setWordWrap(True)
            form.addRow("Imagen", combo)
            form.addRow("Vista previa", preview)
            folders.addLayout(form)
            index = len(self.rows)
            self.rows.append((folder, combo, preview))
            self._valid[index] = False
            combo.currentIndexChanged.connect(lambda _value, row=index: self._update(row))
        scroll.setWidget(content)
        layout.addWidget(scroll)
        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel, self
        )
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Usar selección")
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(False)
        layout.addWidget(self.buttons)

    def _update(self, index: int) -> None:
        folder, combo, preview = self.rows[index]
        selected = combo.currentIndex()
        preview.clear()
        valid = selected == 1
        if selected >= 2:
            candidate = folder.candidates[selected - 2]
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
                    reader.size().scaled(200, 160, Qt.AspectRatioMode.KeepAspectRatio)
                )
                picture = reader.read()
                buffer.close()
                buffer.deleteLater()
                valid = not picture.isNull()
                if valid:
                    preview.setPixmap(QPixmap.fromImage(picture))
                else:
                    preview.setText(
                        "No se puede decodificar esta imagen. Elige otra o conserva la portada."
                    )
        self._valid[index] = valid
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(
            all(self._valid.values())
        )

    def choices(self) -> tuple[CoverChoice, ...]:
        return tuple(
            CoverChoice(
                folder.path,
                None
                if combo.currentIndex() == 1
                else folder.candidates[combo.currentIndex() - 2].path,
            )
            for folder, combo, _ in self.rows
        )
