"""A Qt table adapter for immutable, lightweight catalog summaries."""

from __future__ import annotations

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QObject, QPersistentModelIndex, Qt

from trackfolio.domain.catalog import CatalogSummary

_ROOT_INDEX = QModelIndex()


class CatalogTableModel(QAbstractTableModel):
    """Display catalog data without opening files or consulting persistence."""

    HEADERS = ("Canción", "Artista(s)", "Álbum", "Año", "Archivo")

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._rows: tuple[CatalogSummary, ...] = ()

    def set_summaries(self, rows: tuple[CatalogSummary, ...]) -> None:
        self.beginResetModel()
        self._rows = rows
        self.endResetModel()

    def summaries(self) -> tuple[CatalogSummary, ...]:
        return self._rows

    def update_summary(self, summary: CatalogSummary) -> bool:
        """Actualizar una canción conservando la selección y el resto de la lista."""
        row = self.row_for_file(summary.file_id)
        if row is None:
            return False
        rows = list(self._rows)
        rows[row] = summary
        self._rows = tuple(rows)
        self.dataChanged.emit(self.index(row, 0), self.index(row, self.columnCount() - 1))
        return True

    def file_id_at(self, row: int) -> int | None:
        return self._rows[row].file_id if 0 <= row < len(self._rows) else None

    def row_for_file(self, file_id: int | None) -> int | None:
        return next((index for index, row in enumerate(self._rows) if row.file_id == file_id), None)

    def rowCount(self, parent: QModelIndex | QPersistentModelIndex = _ROOT_INDEX) -> int:
        return 0 if parent.isValid() else len(self._rows)

    def columnCount(self, parent: QModelIndex | QPersistentModelIndex = _ROOT_INDEX) -> int:
        return 0 if parent.isValid() else len(self.HEADERS)

    def data(
        self,
        index: QModelIndex | QPersistentModelIndex,
        role: int = Qt.ItemDataRole.DisplayRole,
    ) -> str | int | None:
        if not index.isValid() or not 0 <= index.row() < len(self._rows):
            return None
        row = self._rows[index.row()]
        if role == Qt.ItemDataRole.UserRole:
            return row.file_id
        if role == Qt.ItemDataRole.TextAlignmentRole and index.column() == 3:
            return int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        if role not in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.ToolTipRole):
            return None
        values = (
            row.title or "",
            "; ".join(row.artists),
            row.album or "",
            str(row.album_year) if row.album_year is not None else "",
            row.relative_path,
        )
        return values[index.column()] if 0 <= index.column() < len(values) else None

    def headerData(
        self,
        section: int,
        orientation: Qt.Orientation,
        role: int = Qt.ItemDataRole.DisplayRole,
    ) -> str | None:
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return self.HEADERS[section] if 0 <= section < len(self.HEADERS) else None
        return None
