"""Scale catalogue artwork without reopening the music file."""

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QPixmap, QResizeEvent
from PySide6.QtWidgets import QLabel, QWidget


class CoverLabel(QLabel):
    """Scale a cover from the catalog, preserving aspect ratio at each screen scale."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("Cover")
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setFixedSize(184, 184)
        self.setAccessibleName("Album cover")
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
