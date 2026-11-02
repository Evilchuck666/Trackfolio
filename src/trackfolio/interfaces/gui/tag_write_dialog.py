"""Review saved values before publishing audio tags; render progress and recovery."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from PySide6.QtCore import QSignalBlocker, Qt, Signal
from PySide6.QtGui import QCloseEvent, QGuiApplication
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from trackfolio.domain.catalog_edit import EDIT_FIELDS, EditField
from trackfolio.domain.tag_write import (
    PendingTagOperation,
    TagWritePreview,
    TagWriteProgress,
    TagWriteReport,
    TagWriteRequest,
)

FIELD_LABELS = {
    "title": "Canción",
    "artists": "Artistas",
    "album": "Álbum",
    "album_year": "Año",
    "track_number": "Pista",
    "track_total": "Total de pistas",
    "disc_number": "Disco",
    "disc_total": "Total de discos",
    "genres": "Géneros",
    "lyrics": "Líricas",
}
_STATES = {
    "ready": "Listo",
    "unchanged": "Sin cambios",
    "blocked": "No escribible",
    "conflict": "Conflicto",
    "confirmed": "Escrito y confirmado",
    "catalog_pending": "Archivo escrito / catálogo pendiente",
    "excluded": "Excluido",
    "failed": "Fallido",
    "pending": "Pendiente",
}


def report_text(report: TagWriteReport) -> str:
    lines = ["Escritura de etiquetas" + (" · Cancelada" if report.cancelled else "")]
    if report.fatal_error:
        lines.append(report.fatal_error)
    for item in report.results:
        lines.append(f"\n{item.path}\n{_STATES[item.state]}")
        if item.message:
            lines.append(item.message)
        if item.backup_path:
            lines.append(f"Respaldo: {item.backup_path}")
    if report.journal_path:
        lines.append(f"\nRegistro de recuperación: {report.journal_path}")
    return "\n".join(lines)


def _plain_label(text: str, parent: QWidget) -> QLabel:
    label = QLabel(text, parent)
    label.setTextFormat(Qt.TextFormat.PlainText)
    label.setWordWrap(True)
    return label


class TagWriteDialog(QDialog):
    preview_requested = Signal(object)
    write_requested = Signal(object, object)
    cancel_requested = Signal()
    recovery_requested = Signal()

    def __init__(
        self, database: Path, file_ids: tuple[int, ...], parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Escribir etiquetas en los archivos")
        self.setModal(True)
        self.resize(860, 760)
        self.setMinimumSize(700, 580)
        self._database, self._file_ids = database, file_ids
        self._preview: TagWritePreview | None = None
        self._report: TagWriteReport | None = None
        self._valid = False
        self._busy = False
        self._lyrics: dict[int, str] = {}
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        self.heading = _plain_label("Escribir etiquetas", self)
        self.heading.setObjectName("PageTitle")
        layout.addWidget(self.heading)
        layout.addWidget(
            _plain_label(
                "Elige qué campos del catálogo quieres escribir. "
                "Un campo vacío marcado se borrará. "
                "Cada canción conservará sus propios valores. "
                "Se creará un respaldo junto al original.",
                self,
            )
        )
        grid = QGridLayout()
        self.fields: dict[EditField, QCheckBox] = {}
        for index, field in enumerate(EDIT_FIELDS):
            checkbox = QCheckBox(FIELD_LABELS[field], self)
            checkbox.toggled.connect(self._invalidate)
            self.fields[field] = checkbox
            grid.addWidget(checkbox, index // 5, index % 5)
        layout.addLayout(grid)
        self.date_loss = QCheckBox(
            "Permitir sustituir una fecha inválida por solo el año o eliminarla", self
        )
        self.date_loss.toggled.connect(self._invalidate)
        layout.addWidget(self.date_loss)
        row = QHBoxLayout()
        self.preview_button = QPushButton("Revisar diferencias", self)
        self.preview_button.clicked.connect(self._request_preview)
        self.recovery_button = QPushButton("Operaciones pendientes…", self)
        self.recovery_button.clicked.connect(self.recovery_requested.emit)
        row.addWidget(self.preview_button)
        row.addStretch()
        row.addWidget(self.recovery_button)
        layout.addLayout(row)
        self.table = QTableWidget(0, 4, self)
        self.table.setHorizontalHeaderLabels(["Escribir", "Archivo", "Estado", "Formato"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.setColumnWidth(0, 65)
        self.table.setColumnWidth(2, 125)
        self.table.setColumnWidth(3, 100)
        self.table.itemChanged.connect(self._update_actions)
        self.table.currentCellChanged.connect(self._show_item)
        layout.addWidget(self.table, 1)
        self.lyrics_combo = QComboBox(self)
        self.lyrics_combo.setAccessibleName("Idioma y descripción de las letras a modificar")
        self.lyrics_combo.currentIndexChanged.connect(self._lyrics_changed)
        self.lyrics_combo.hide()
        layout.addWidget(self.lyrics_combo)
        self.details = QPlainTextEdit(self)
        self.details.setReadOnly(True)
        self.details.setMinimumHeight(120)
        layout.addWidget(self.details, 1)
        self.summary = _plain_label(
            "Marca los campos y revisa las diferencias antes de escribir.", self
        )
        layout.addWidget(self.summary)
        self.progress = QProgressBar(self)
        self.progress.hide()
        layout.addWidget(self.progress)
        self.error = _plain_label("", self)
        self.error.setObjectName("ErrorMessage")
        self.error.hide()
        layout.addWidget(self.error)
        buttons = QHBoxLayout()
        self.copy_button = QPushButton("Copiar informe", self)
        self.copy_button.clicked.connect(
            lambda: QGuiApplication.clipboard().setText(self.details.toPlainText())
        )
        self.export_button = QPushButton("Guardar informe…", self)
        self.export_button.clicked.connect(self._export_report)
        buttons.addWidget(self.copy_button)
        buttons.addWidget(self.export_button)
        buttons.addStretch()
        self.close_button = QPushButton("Cerrar", self)
        self.close_button.clicked.connect(self.reject)
        self.write_button = QPushButton("Escribir etiquetas", self)
        self.write_button.setObjectName("PrimaryButton")
        self.write_button.clicked.connect(self._request_write)
        buttons.addWidget(self.close_button)
        buttons.addWidget(self.write_button)
        layout.addLayout(buttons)
        self._update_actions()

    def request(self) -> TagWriteRequest:
        return TagWriteRequest(
            self._database,
            self._file_ids,
            tuple(field for field, widget in self.fields.items() if widget.isChecked()),
            self.date_loss.isChecked(),
            tuple(sorted(self._lyrics.items())),
        )

    def _invalidate(self, *_args: object) -> None:
        self._valid = False
        self.summary.setText(
            "Revisa de nuevo las diferencias para aplicar esta selección de campos."
        )
        self.error.hide()
        self._update_actions()

    def _request_preview(self) -> None:
        self._report = None
        self.set_busy(True)
        self.preview_requested.emit(self.request())

    def selected_ids(self) -> tuple[int, ...]:
        if self._preview is None:
            return ()
        return tuple(
            item.file_id
            for row, item in enumerate(self._preview.items)
            if item.state == "ready"
            and (cell := self.table.item(row, 0)) is not None
            and cell.checkState() == Qt.CheckState.Checked
        )

    def set_preview(self, preview: TagWritePreview) -> None:
        self._preview, self._valid, self._busy = preview, True, False
        blocker = QSignalBlocker(self.table)
        self.table.setRowCount(len(preview.items))
        for row, item in enumerate(preview.items):
            check = QTableWidgetItem()
            if item.state == "ready":
                check.setFlags(check.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                check.setCheckState(Qt.CheckState.Checked)
            else:
                check.setFlags(Qt.ItemFlag.ItemIsEnabled)
            self.table.setItem(row, 0, check)
            self.table.setItem(row, 1, QTableWidgetItem(str(item.path)))
            self.table.setItem(row, 2, QTableWidgetItem(_STATES[item.state]))
            self.table.setItem(row, 3, QTableWidgetItem(item.tags.version if item.tags else ""))
        del blocker
        if preview.items:
            self.table.selectRow(0)
            self._show_item()
        self.progress.hide()
        self._update_actions()

    def _show_item(self, *_args: object) -> None:
        if self._preview is None or self._report is not None:
            return
        row = self.table.currentRow()
        if not 0 <= row < len(self._preview.items):
            return
        item = self._preview.items[row]
        lines = [str(item.path), item.message]
        if item.tags:
            for difference in item.tags.differences:
                before = json.dumps(difference.before, ensure_ascii=False)
                after = json.dumps(difference.after, ensure_ascii=False)
                lines.append(f"\n{FIELD_LABELS[difference.field]}: {before} → {after}")
                lines.append("Etiquetas afectadas: " + ", ".join(difference.physical_tags))
            if item.tags.before_date != item.tags.after_date:
                lines.append(
                    f"\nFecha completa: {item.tags.before_date or '(vacía)'} "
                    f"→ {item.tags.after_date or '(vacía)'}"
                )
            operation = self._preview.operation_id
            backup = (
                item.path.parent
                / ".trackfolio-backups"
                / operation
                / f"{item.file_id}-{item.path.name}.tfo-bak"
            )
            lines.append(f"\nRespaldo: {backup}")
        self.details.setPlainText("\n".join(lines))
        blocker = QSignalBlocker(self.lyrics_combo)
        self.lyrics_combo.clear()
        candidates = item.tags.lyrics_keys if item.tags else ()
        if len(candidates) > 1:
            self.details.appendPlainText(
                "\nSe conserva el resto de idiomas. Al reimportar, el lector puede mostrar "
                "otra de las versiones de letras que permanezcan en el archivo."
            )
        self.lyrics_combo.addItem("Elige idioma y descripción de las letras", None)
        for key in candidates:
            parts = key.split(":")
            self.lyrics_combo.addItem(
                f"{parts[-1]} — {':'.join(parts[1:-1]) or 'sin descripción'}", key
            )
        selected = self._lyrics.get(item.file_id)
        self.lyrics_combo.setCurrentIndex(max(0, self.lyrics_combo.findData(selected)))
        self.lyrics_combo.setVisible(len(candidates) > 1)
        del blocker

    def _lyrics_changed(self, index: int) -> None:
        if self._preview is not None and self.table.currentRow() >= 0:
            item = self._preview.items[self.table.currentRow()]
            key = self.lyrics_combo.itemData(index)
            if isinstance(key, str):
                self._lyrics[item.file_id] = key
            else:
                self._lyrics.pop(item.file_id, None)
            self._invalidate()

    def _request_write(self) -> None:
        if self._preview is not None and self._valid:
            ids = self.selected_ids()
            if ids:
                self.set_busy(True)
                self.write_requested.emit(self._preview, ids)

    def set_busy(self, busy: bool) -> None:
        self._busy = busy
        self.error.hide()
        self.progress.setVisible(busy)
        if busy:
            self.progress.setRange(0, 0)
        self.close_button.setText("Cancelar operación" if busy else "Cerrar")
        self._update_actions()

    def set_progress(self, progress: TagWriteProgress) -> None:
        names = {
            "preview": "Preparando vista previa",
            "reading": "Leyendo y verificando",
            "checking": "Comprobando cambios",
            "backup": "Creando respaldo",
            "writing": "Escribiendo y verificando",
            "finished": "Operación terminada",
        }
        self.summary.setText(
            f"{names.get(progress.phase, progress.phase)} · "
            f"{progress.processed}/{progress.total}\n{progress.path or ''}"
        )

    def set_error(self, message: str) -> None:
        self.set_busy(False)
        self._valid = False
        self.error.setText(message)
        self.error.show()
        self._update_actions()

    def set_report(self, report: TagWriteReport) -> None:
        self._report, self._valid = report, False
        self.set_busy(False)
        self.lyrics_combo.hide()
        self.details.setPlainText(report_text(report))
        if self._preview is not None:
            states = {item.file_id: item.state for item in report.results}
            blocker = QSignalBlocker(self.table)
            for row, item in enumerate(self._preview.items):
                self.table.setItem(row, 2, QTableWidgetItem(_STATES[states[item.file_id]]))
            del blocker
        written = sum(item.state in ("confirmed", "catalog_pending") for item in report.results)
        self.summary.setText(
            f"{'Operación cancelada' if report.cancelled else 'Operación terminada'} · "
            f"{written} archivos escritos. Los respaldos se conservan."
        )
        self._update_actions()

    def _update_actions(self, *_args: object) -> None:
        for widget in [*self.fields.values(), self.date_loss, self.table, self.lyrics_combo]:
            widget.setEnabled(not self._busy)
        self.preview_button.setEnabled(
            not self._busy and any(field.isChecked() for field in self.fields.values())
        )
        self.recovery_button.setEnabled(not self._busy)
        self.write_button.setEnabled(not self._busy and self._valid and bool(self.selected_ids()))
        self.copy_button.setEnabled(not self._busy and self._report is not None)
        self.export_button.setEnabled(self.copy_button.isEnabled())
        if not self._busy and self._valid and self._preview:
            selected = set(self.selected_ids())
            items = [item for item in self._preview.items if item.file_id in selected]
            cleared = sum(
                diff.after in (None, ())
                for item in items
                if item.tags
                for diff in item.tags.differences
            )
            sizes = [item.fingerprint.size for item in items if item.fingerprint]
            required = sum(sizes) + max(sizes, default=0)
            self.summary.setText(
                f"{len(items)} archivos seleccionados · {cleared} campos se borrarán.\n"
                f"Espacio estimado para respaldos y temporal: {required / 1024**2:.1f} MiB. "
                "Revisa las diferencias antes de confirmar."
            )

    def _export_report(self) -> None:
        if self._report is None:
            return
        dialog = QFileDialog(
            self, "Guardar informe de escritura", str(Path.home() / "escritura-etiquetas.json")
        )
        dialog.setOption(QFileDialog.Option.DontUseNativeDialog, True)
        dialog.setAcceptMode(QFileDialog.AcceptMode.AcceptSave)
        dialog.setDefaultSuffix("json")
        dialog.setNameFilter("Informe JSON (*.json)")
        if dialog.exec() == QDialog.DialogCode.Accepted and dialog.selectedFiles():
            try:
                Path(dialog.selectedFiles()[0]).write_text(
                    json.dumps(asdict(self._report), ensure_ascii=False, indent=2, default=str)
                    + "\n",
                    encoding="utf-8",
                )
            except OSError as exc:
                self.set_error(f"No se pudo guardar el informe: {exc}")
        dialog.deleteLater()

    def reject(self) -> None:
        if self._busy:
            self.cancel_requested.emit()
            self.summary.setText(
                "Cancelando… Se espera a que el archivo en curso quede en un estado seguro."
            )
        else:
            super().reject()

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._busy:
            self.reject()
            event.ignore()
        else:
            super().closeEvent(event)


class TagRecoveryDialog(QDialog):
    review_requested = Signal(object, bool)
    cancel_requested = Signal()

    def __init__(self, operations: tuple[PendingTagOperation, ...], parent: QWidget) -> None:
        super().__init__(parent)
        self.setWindowTitle("Operaciones de etiquetas pendientes")
        self.setModal(True)
        self.resize(760, 520)
        self._busy = False
        self._reviewed: Path | None = None
        layout = QVBoxLayout(self)
        layout.addWidget(
            _plain_label(
                "Hay operaciones que necesitan revisión. No se reanudarán escrituras "
                "ni se restaurarán archivos automáticamente.",
                self,
            )
        )
        self.operations = QComboBox(self)
        for operation in operations:
            self.operations.addItem(
                f"{operation.database_path or 'Catálogo desconocido'} — "
                f"{operation.journal_path.parent.name}",
                operation.journal_path,
            )
        layout.addWidget(self.operations)
        self.details = QPlainTextEdit(self)
        self.details.setReadOnly(True)
        self.details.setPlainText(
            "\n\n".join(f"{item.journal_path}\n{item.description}" for item in operations)
        )
        layout.addWidget(self.details)
        row = QHBoxLayout()
        self.review_button = QPushButton("Revisar archivos", self)
        self.confirm_button = QPushButton("Confirmar observaciones verificadas", self)
        self.confirm_button.setEnabled(False)
        close = QPushButton("Cerrar", self)
        close.clicked.connect(self.reject)
        self.review_button.clicked.connect(lambda: self._request(False))
        self.confirm_button.clicked.connect(lambda: self._request(True))
        self.operations.currentIndexChanged.connect(lambda: self.confirm_button.setEnabled(False))
        row.addWidget(self.review_button)
        row.addWidget(self.confirm_button)
        row.addWidget(close)
        layout.addLayout(row)

    def _request(self, reconcile: bool) -> None:
        self._busy = True
        self.review_button.setEnabled(False)
        self.confirm_button.setEnabled(False)
        self.operations.setEnabled(False)
        self.details.setPlainText("Revisando los archivos y sus observaciones…")
        self.review_requested.emit(self.operations.currentData(), reconcile)

    def set_report(self, report: TagWriteReport) -> None:
        self._busy = False
        self.details.setPlainText(report_text(report))
        self._reviewed = report.journal_path
        self.operations.setEnabled(True)
        self.review_button.setEnabled(True)
        self.confirm_button.setEnabled(
            any(item.state in ("catalog_pending", "pending") for item in report.results)
        )

    def set_error(self, message: str) -> None:
        self._busy = False
        self.details.setPlainText(message)
        self.operations.setEnabled(True)
        self.review_button.setEnabled(True)

    def reject(self) -> None:
        if self._busy:
            self.cancel_requested.emit()
            self.details.setPlainText("Cancelando la revisión…")
        else:
            super().reject()

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._busy:
            event.ignore()
        else:
            super().closeEvent(event)
