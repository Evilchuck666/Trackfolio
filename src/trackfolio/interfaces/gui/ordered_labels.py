"""An ordered collection of complete names, without delimiter-based parsing."""

from __future__ import annotations

from collections.abc import Iterable

from PySide6.QtCore import QStringListModel, Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCompleter,
    QHBoxLayout,
    QLineEdit,
    QListWidget,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class OrderedLabels(QWidget):
    """Add, remove and reorder names while retaining their exact spelling."""

    changed = Signal()
    suggestion_requested = Signal(str)

    def __init__(self, label: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("OrderedLabels")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        self.list = QListWidget(self)
        self.list.setAccessibleName(label)
        self.list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.list.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.list.setMaximumHeight(84)
        self.list.setMinimumHeight(54)
        layout.addWidget(self.list)
        entry = QHBoxLayout()
        entry.setSpacing(6)
        self.name_edit = QLineEdit(self)
        self.name_edit.setAccessibleName(f"Añadir a {label.lower()}")
        self.name_edit.setPlaceholderText("Nombre completo")
        self.name_edit.textChanged.connect(self._update_actions)
        self.name_edit.textEdited.connect(self.suggestion_requested.emit)
        self.name_edit.returnPressed.connect(self.add_name)
        self._suggestions = QStringListModel(self)
        self.completer = QCompleter(self._suggestions, self)
        self.completer.setCaseSensitivity(Qt.CaseSensitivity.CaseSensitive)
        self.completer.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
        self.completer.setFilterMode(Qt.MatchFlag.MatchContains)
        self.name_edit.setCompleter(self.completer)
        self.add_button = QPushButton("Añadir", self)
        self.add_button.clicked.connect(self.add_name)
        entry.addWidget(self.name_edit, 1)
        entry.addWidget(self.add_button)
        layout.addLayout(entry)
        actions = QHBoxLayout()
        actions.setSpacing(6)
        self.remove_button = QPushButton("Quitar", self)
        self.up_button = QPushButton("↑", self)
        self.down_button = QPushButton("↓", self)
        self.up_button.setAccessibleName(f"Subir {label.lower()}")
        self.up_button.setToolTip("Mover el nombre hacia arriba")
        self.down_button.setAccessibleName(f"Bajar {label.lower()}")
        self.down_button.setToolTip("Mover el nombre hacia abajo")
        self.remove_button.clicked.connect(self.remove_name)
        self.up_button.clicked.connect(lambda: self.move_name(-1))
        self.down_button.clicked.connect(lambda: self.move_name(1))
        actions.addWidget(self.remove_button)
        actions.addWidget(self.up_button)
        actions.addWidget(self.down_button)
        actions.addStretch()
        layout.addLayout(actions)
        self.list.currentRowChanged.connect(self._update_actions)
        self._update_actions()

    def names(self) -> tuple[str, ...]:
        return tuple(self.list.item(row).text() for row in range(self.list.count()))

    def set_names(self, names: Iterable[str]) -> None:
        """Populate a draft without generating user edits or normalizing stored values."""
        self.list.clear()
        self.list.addItems(list(names))
        self.name_edit.clear()
        if self.list.count():
            self.list.setCurrentRow(0)
        self._update_actions()

    def set_suggestions(self, names: Iterable[str]) -> None:
        self._suggestions.setStringList(list(dict.fromkeys(names)))
        if self.name_edit.hasFocus() and self.name_edit.text():
            self.completer.setCompletionPrefix(self.name_edit.text())
            self.completer.complete()

    def add_name(self) -> None:
        value = self.name_edit.text()
        if not self.isEnabled() or not value.strip():
            return
        names = self.names()
        if value in names:
            self.list.setCurrentRow(names.index(value))
            self.name_edit.clear()
            return
        self.list.addItem(value)
        self.list.setCurrentRow(self.list.count() - 1)
        self.name_edit.clear()
        self.changed.emit()
        self._update_actions()

    def remove_name(self) -> None:
        row = self.list.currentRow()
        if not self.isEnabled() or row < 0:
            return
        self.list.takeItem(row)
        self.changed.emit()
        self._update_actions()

    def move_name(self, offset: int) -> None:
        row = self.list.currentRow()
        destination = row + offset
        if not self.isEnabled() or not 0 <= destination < self.list.count():
            return
        item = self.list.takeItem(row)
        self.list.insertItem(destination, item)
        self.list.setCurrentRow(destination)
        self.changed.emit()
        self._update_actions()

    def _update_actions(self) -> None:
        row = self.list.currentRow()
        self.add_button.setEnabled(bool(self.name_edit.text().strip()))
        self.remove_button.setEnabled(row >= 0)
        self.up_button.setEnabled(row > 0)
        self.down_button.setEnabled(0 <= row < self.list.count() - 1)
