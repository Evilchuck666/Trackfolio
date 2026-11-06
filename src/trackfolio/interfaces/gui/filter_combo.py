"""Song filter selector using the application-wide combo box theme."""

from PySide6.QtWidgets import QComboBox, QWidget


class FilterComboBox(QComboBox):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("SongFilter")
