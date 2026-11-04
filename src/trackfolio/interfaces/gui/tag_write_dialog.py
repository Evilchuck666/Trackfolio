"""Write saved song metadata with a fixed list, progress and optional error report."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from trackfolio.domain.catalog import CatalogSummary
from trackfolio.domain.tag_write import TagWriteProgress, TagWriteReport

_STATES = {
    "unchanged": "Sin cambios",
    "conflict": "Conflicto",
    "confirmed": "Escrito",
    "catalog_pending": "Archivo escrito / catálogo pendiente",
    "excluded": "No escribible",
    "failed": "Fallido",
    "pending": "Pendiente",
}

_NFO_STATES = {
    "updated": "NFO actualizado",
    "unchanged": "NFO sin cambios",
    "absent": "NFO ausente",
    "pending": "NFO pendiente",
    "conflict": "Conflicto NFO",
    "failed": "NFO fallido",
}

_COVER_STATES = {
    "preserved": "Portada conservada",
    "embedded": "Portada incrustada",
    "replaced": "Portada sustituida",
    "unchanged": "Portada ya coincidente",
    "skipped": "Portada conservada por elección",
}


def report_text(report: TagWriteReport) -> str:
    lines = ["Escritura de etiquetas" + (" · Cancelada" if report.cancelled else "")]
    if report.fatal_error:
        lines.append(report.fatal_error)
    for item in report.results:
        lines.append(f"\n{item.path}\n{_STATES[item.state]}")
        if item.message:
            lines.append(item.message)
        if item.cover_action != "preserved" or item.cover_path:
            lines.append(_COVER_STATES[item.cover_action])
            if item.cover_path:
                lines.append(f"Imagen fuente: {item.cover_path}")
        if item.backup_path:
            lines.append(f"Respaldo: {item.backup_path}")
    for nfo in report.nfo_results:
        lines.append(f"\n{nfo.path}\n{_NFO_STATES[nfo.state]}")
        if nfo.message:
            lines.append(nfo.message)
        if nfo.backup_path:
            lines.append(f"Respaldo: {nfo.backup_path}")
    if report.journal_path:
        lines.append(f"\nRegistro de recuperación: {report.journal_path}")
    return "\n".join(lines)


class TagWriteDialog(QDialog):
    write_requested = Signal()
    cancel_requested = Signal()

    def __init__(
        self,
        database: Path,
        songs: tuple[CatalogSummary, ...],
        parent: QWidget | None = None,
        *,
        all_catalog: bool = False,
    ) -> None:
        super().__init__(parent)
        title = "Escribir etiquetas de todo el catálogo" if all_catalog else "Escribir etiquetas"
        self.setWindowTitle(title)
        self.setModal(True)
        self.resize(800, 600)
        self.setMinimumSize(640, 480)
        self.database_path = database
        self.file_ids = tuple(song.file_id for song in songs)
        self._rows = {song.file_id: row for row, song in enumerate(songs)}
        self._report: TagWriteReport | None = None
        self._error_message = ""
        self._busy = False
        self._completed = False
        self._close_pending = False
        self._error_popup: QMessageBox | None = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        heading = QLabel(title, self)
        heading.setObjectName("PageTitle")
        layout.addWidget(heading)
        description = QLabel(
            "Se actualizarán las etiquetas, la portada disponible y album.nfo si existe. "
            "Si hay varias imágenes, podrás elegir una.",
            self,
        )
        description.setWordWrap(True)
        layout.addWidget(description)
        self.table = QTableWidget(len(songs), 4, self)
        self.table.setHorizontalHeaderLabels(["Canción", "Artista(s)", "Archivo", "Estado"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        for row, song in enumerate(songs):
            for column, value in enumerate(
                (
                    song.title or Path(song.relative_path).name,
                    "; ".join(song.artists),
                    song.relative_path,
                    "Pendiente",
                )
            ):
                cell = QTableWidgetItem(value)
                cell.setToolTip(value)
                self.table.setItem(row, column, cell)
        layout.addWidget(self.table, 3)
        self.output = QPlainTextEdit(self)
        self.output.setReadOnly(True)
        self.output.setAccessibleName("Progreso de escritura de etiquetas")
        layout.addWidget(self.output, 2)
        self.summary = QLabel(f"{len(songs)} canciones para escribir.", self)
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)
        self.progress = QProgressBar(self)
        self.progress.setRange(0, len(songs))
        self.progress.setValue(0)
        layout.addWidget(self.progress)
        buttons = QHBoxLayout()
        buttons.addStretch()
        self.close_button = QPushButton("Cerrar", self)
        self.close_button.clicked.connect(self.reject)
        self.write_button = QPushButton("Escribir etiquetas", self)
        self.write_button.setObjectName("PrimaryButton")
        self.write_button.clicked.connect(self._request_write)
        self.write_button.setEnabled(bool(songs))
        buttons.addWidget(self.close_button)
        buttons.addWidget(self.write_button)
        layout.addLayout(buttons)

    def _request_write(self) -> None:
        if self._busy or self._completed or not self.file_ids:
            return
        self._report = None
        self._error_message = ""
        self.output.clear()
        self.set_busy(True)
        for row in range(self.table.rowCount()):
            cell = self.table.item(row, 3)
            assert cell is not None
            cell.setText("Pendiente")
        self.progress.setRange(0, 0)
        self.summary.setText("Preparando escritura…")
        self.write_requested.emit()

    def set_busy(self, busy: bool) -> None:
        self._busy = busy
        self.write_button.setEnabled(bool(self.file_ids) and not busy and not self._completed)

    def set_progress(self, progress: TagWriteProgress) -> None:
        names = {
            "preview": "Preparando canciones",
            "cover_discovery": "Buscando portadas",
            "reading": "Leyendo etiquetas",
            "checking": "Comprobando archivo",
            "backup": "Creando respaldo",
            "writing": "Escribiendo y verificando",
            "nfo_reading": "Comprobando album.nfo",
            "nfo_writing": "Actualizando album.nfo",
            "finished": "Escritura terminada",
        }
        phase = names.get(progress.phase, progress.phase)
        text = f"{phase} · {progress.processed}/{progress.total}"
        if progress.path is not None:
            text += f" · {progress.path}"
        self.summary.setText(text)
        self.output.appendPlainText(text)
        self.progress.setRange(0, max(1, progress.total))
        self.progress.setValue(progress.processed)

    def set_error(self, message: str, *, offer_report: bool = True) -> None:
        self._completed = False
        self.set_busy(False)
        self._error_message = message
        self.output.appendPlainText(message)
        self.summary.setText("No se pudo completar la escritura.")
        self.progress.setRange(0, max(1, len(self.file_ids)))
        if self._close_pending:
            super().reject()
        elif offer_report:
            self._offer_error_report()

    def set_report(self, report: TagWriteReport, *, offer_report: bool = True) -> None:
        self._report = report
        self._completed = (
            not report.cancelled
            and not report.fatal_error
            and {item.file_id for item in report.results} == set(self.file_ids)
            and all(item.state in ("confirmed", "unchanged") for item in report.results)
            and all(item.state in ("updated", "unchanged", "absent") for item in report.nfo_results)
        )
        self.set_busy(False)
        if report.fatal_error:
            self.output.appendPlainText(report.fatal_error)
        for item in report.results:
            self.output.appendPlainText(f"{item.path} · {_STATES[item.state]}")
            if item.message:
                self.output.appendPlainText(item.message)
            if item.cover_action != "preserved" or item.cover_path:
                self.output.appendPlainText(_COVER_STATES[item.cover_action])
                if item.cover_path:
                    self.output.appendPlainText(f"Imagen fuente: {item.cover_path}")
            if (row := self._rows.get(item.file_id)) is not None:
                cell = self.table.item(row, 3)
                assert cell is not None
                cell.setText(_STATES[item.state])
                cell.setToolTip(item.message)
        for nfo in report.nfo_results:
            self.output.appendPlainText(f"{nfo.path} · {_NFO_STATES[nfo.state]}")
            if nfo.message:
                self.output.appendPlainText(nfo.message)
            if nfo.backup_path:
                self.output.appendPlainText(f"Respaldo: {nfo.backup_path}")
        written = sum(item.state in ("confirmed", "catalog_pending") for item in report.results)
        self.summary.setText(
            f"{'Escritura cancelada' if report.cancelled else 'Escritura terminada'} · "
            f"{written} archivos escritos."
            + (
                f" {sum(n.state == 'updated' for n in report.nfo_results)} NFO actualizados."
                if report.nfo_results
                else ""
            )
        )
        self.progress.setRange(0, max(1, len(self.file_ids)))
        self.progress.setValue(sum(item.state != "pending" for item in report.results))
        if self._close_pending:
            super().reject()
        elif offer_report and (
            report.fatal_error
            or any(
                item.state in ("failed", "conflict", "catalog_pending")
                or (item.state == "excluded" and item.message)
                for item in report.results
            )
            or any(
                item.state in ("failed", "conflict")
                or (item.state == "pending" and not report.cancelled)
                for item in report.nfo_results
            )
        ):
            self._offer_error_report()

    def _offer_error_report(self) -> None:
        popup = QMessageBox(self)
        popup.setWindowTitle("Error al escribir etiquetas")
        popup.setIcon(QMessageBox.Icon.Warning)
        popup.setText("La operación terminó con errores.")
        popup.setInformativeText(
            "Puedes guardar el informe con los errores y las rutas de respaldo."
        )
        popup.setDetailedText(report_text(self._report) if self._report else self._error_message)
        save = popup.addButton("Guardar informe…", QMessageBox.ButtonRole.ActionRole)
        popup.addButton("Cerrar", QMessageBox.ButtonRole.RejectRole)
        popup.buttonClicked.connect(
            lambda button: self._export_report() if button is save else None
        )

        def closed(_result: int) -> None:
            self._error_popup = None
            popup.deleteLater()

        popup.finished.connect(closed)
        self._error_popup = popup
        popup.open()

    def _export_report(self) -> None:
        dialog = QFileDialog(
            self, "Guardar informe de escritura", str(Path.home() / "escritura-etiquetas.json")
        )
        dialog.setOption(QFileDialog.Option.DontUseNativeDialog, True)
        dialog.setAcceptMode(QFileDialog.AcceptMode.AcceptSave)
        dialog.setDefaultSuffix("json")
        dialog.setNameFilter("Informe JSON (*.json)")
        if dialog.exec() == QDialog.DialogCode.Accepted and dialog.selectedFiles():
            payload = (
                asdict(self._report)
                if self._report
                else {
                    "error": self._error_message,
                    "database": self.database_path,
                    "file_ids": self.file_ids,
                }
            )
            try:
                Path(dialog.selectedFiles()[0]).write_text(
                    json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n",
                    encoding="utf-8",
                )
            except OSError as exc:
                self.set_error(f"No se pudo guardar el informe: {exc}", offer_report=False)
        dialog.deleteLater()

    def reject(self) -> None:
        if self._busy:
            self._close_pending = True
            self.cancel_requested.emit()
            self.summary.setText("Cerrando… Se espera a que termine el archivo en curso.")
        else:
            super().reject()

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._busy:
            self.reject()
            event.ignore()
        else:
            super().closeEvent(event)
