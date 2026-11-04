"""Filter selector with a packaged arrow independent of the desktop theme."""

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon, QPainter, QPaintEvent
from PySide6.QtWidgets import QComboBox, QStyle, QStyleOptionComboBox, QWidget

from trackfolio.interfaces.gui.theme import icon


class FilterComboBox(QComboBox):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("SongFilter")
        self._arrow = icon("chevron-down")

    def paintEvent(self, event: QPaintEvent) -> None:
        super().paintEvent(event)
        option = QStyleOptionComboBox()
        self.initStyleOption(option)
        area = self.style().subControlRect(
            QStyle.ComplexControl.CC_ComboBox,
            option,
            QStyle.SubControl.SC_ComboBoxArrow,
            self,
        )
        painter = QPainter(self)
        self._arrow.paint(
            painter,
            area.adjusted(7, 7, -7, -7),
            Qt.AlignmentFlag.AlignCenter,
            QIcon.Mode.Normal if self.isEnabled() else QIcon.Mode.Disabled,
        )
        painter.end()
