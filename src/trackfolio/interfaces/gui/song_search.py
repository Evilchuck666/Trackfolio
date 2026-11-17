"""Song search box with a syntax cheat sheet and term-aware autocompletion."""

from __future__ import annotations

from PySide6.QtCore import QStringListModel, Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import QCompleter, QHBoxLayout, QLineEdit, QMenu, QToolButton, QWidget

from trackfolio.domain.song_query import FILTER_REFERENCE, completion_candidates


def current_term_start(text: str, cursor: int) -> int:
    """Start of the term under the cursor; spaces inside quotes or /regex/ don't split terms."""
    start = 0
    delimiter: str | None = None
    for index, char in enumerate(text[:cursor]):
        if delimiter is not None:
            if char == delimiter:
                delimiter = None
        elif char.isspace():
            start = index + 1
        elif char == '"' or (char == "/" and (index == start or text[index - 1] in "-!:")):
            delimiter = char
    return start


class SongSearchField(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        self.line_edit = QLineEdit(self)
        self.help_button = QToolButton(self)
        self.help_button.setText("?")
        self.help_button.setAccessibleName("Search syntax help")
        self.help_button.setToolTip("Show every search filter (F1)")
        self.help_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.help_menu = QMenu(self.help_button)
        self.help_menu.setToolTipsVisible(True)
        for item in FILTER_REFERENCE:
            action = self.help_menu.addAction(f"{item.syntax}\t{item.description}")
            action.setToolTip(f"Insert {item.example}")
            action.setData(item.example)
            action.triggered.connect(
                lambda _checked=False, example=item.example: self.insert_example(example)
            )
        self.help_button.setMenu(self.help_menu)
        layout.addWidget(self.line_edit, 1)
        layout.addWidget(self.help_button)
        shortcut = QShortcut(QKeySequence(QKeySequence.StandardKey.HelpContents), self.line_edit)
        shortcut.setContext(Qt.ShortcutContext.WidgetShortcut)
        shortcut.activated.connect(self.show_help)

        self._vocabulary: tuple[
            tuple[str, ...], tuple[str, ...], tuple[str, ...], tuple[int, ...]
        ] = ((), (), (), ())
        self._suggestions = QStringListModel(self)
        self.completer = QCompleter(self._suggestions, self)
        self.completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.completer.setCompletionMode(QCompleter.CompletionMode.UnfilteredPopupCompletion)
        self.completer.setWidget(self.line_edit)
        self.completer.activated.connect(self.accept_completion)
        self.line_edit.textEdited.connect(self.update_completions)

    def set_vocabulary(
        self,
        genres: tuple[str, ...],
        artists: tuple[str, ...],
        albums: tuple[str, ...],
        years: tuple[int, ...],
    ) -> None:
        self._vocabulary = (genres, artists, albums, years)

    def show_help(self) -> None:
        self.help_menu.popup(self.help_button.mapToGlobal(self.help_button.rect().bottomLeft()))

    def insert_example(self, example: str) -> None:
        text = self.line_edit.text()
        cursor = self.line_edit.cursorPosition()
        before = " " if cursor > 0 and not text[cursor - 1].isspace() else ""
        after = " " if cursor < len(text) and not text[cursor].isspace() else ""
        insertion = before + example + after
        self.line_edit.setText(text[:cursor] + insertion + text[cursor:])
        self.line_edit.setCursorPosition(cursor + len(insertion))
        self.line_edit.setFocus()

    def current_prefix(self) -> str:
        text = self.line_edit.text()
        cursor = self.line_edit.cursorPosition()
        return text[current_term_start(text, cursor) : cursor]

    def update_completions(self, *_args: object) -> None:
        prefix = self.current_prefix()
        if not prefix:
            self._hide_popup()
            return
        candidates = completion_candidates(prefix, *self._vocabulary)
        if candidates == [prefix]:
            candidates = []
        self._suggestions.setStringList(candidates)
        if candidates:
            self.completer.complete()
        else:
            self._hide_popup()

    def _hide_popup(self) -> None:
        popup = self.completer.popup()
        if popup is not None:
            popup.hide()

    def accept_completion(self, completion: str) -> None:
        text = self.line_edit.text()
        cursor = self.line_edit.cursorPosition()
        start = current_term_start(text, cursor)
        end = cursor
        while end < len(text) and not text[end].isspace():
            end += 1
        suffix = "" if completion.endswith(":") else " "
        rest = text[end:]
        if suffix and rest.startswith(" "):
            suffix = ""
        self.line_edit.setText(text[:start] + completion + suffix + rest)
        self.line_edit.setCursorPosition(start + len(completion) + len(suffix))
        if completion.endswith(":"):
            self.update_completions()
