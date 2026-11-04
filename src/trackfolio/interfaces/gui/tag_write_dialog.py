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
    "unchanged": "Unchanged",
    "conflict": "Conflict",
    "confirmed": "Written",
    "catalog_pending": "File written / catalog pending",
    "excluded": "Not writable",
    "failed": "Failed",
    "pending": "Pending",
}

_NFO_STATES = {
    "updated": "NFO updated",
    "unchanged": "NFO unchanged",
    "absent": "NFO absent",
    "pending": "NFO pending",
    "conflict": "NFO conflict",
    "failed": "NFO failed",
}

_COVER_STATES = {
    "preserved": "Cover preserved",
    "embedded": "Cover embedded",
    "replaced": "Cover replaced",
    "unchanged": "Cover already matches",
    "skipped": "Cover preserved by choice",
}


def report_text(report: TagWriteReport) -> str:
    lines = ["Tag writing" + (" · Cancelled" if report.cancelled else "")]
    if report.fatal_error:
        lines.append(report.fatal_error)
    for item in report.results:
        lines.append(f"\n{item.path}\n{_STATES[item.state]}")
        if item.message:
            lines.append(item.message)
        if item.cover_action != "preserved" or item.cover_path:
            lines.append(_COVER_STATES[item.cover_action])
            if item.cover_path:
                lines.append(f"Source image: {item.cover_path}")
        if item.backup_path:
            lines.append(f"Backup: {item.backup_path}")
    for nfo in report.nfo_results:
        lines.append(f"\n{nfo.path}\n{_NFO_STATES[nfo.state]}")
        if nfo.message:
            lines.append(nfo.message)
        if nfo.backup_path:
            lines.append(f"Backup: {nfo.backup_path}")
    if report.journal_path:
        lines.append(f"\nRecovery log: {report.journal_path}")
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
        title = "Write tags for the entire catalog" if all_catalog else "Write tags"
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
            "Tags, available artwork and album.nfo (if present) will be updated. "
            "If there are multiple images, you can choose one.",
            self,
        )
        description.setWordWrap(True)
        layout.addWidget(description)
        self.table = QTableWidget(len(songs), 4, self)
        self.table.setHorizontalHeaderLabels(["Song", "Artist(s)", "File", "Status"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        for row, song in enumerate(songs):
            for column, value in enumerate(
                (
                    song.title or Path(song.relative_path).name,
                    "; ".join(song.artists),
                    song.relative_path,
                    "Pending",
                )
            ):
                cell = QTableWidgetItem(value)
                cell.setToolTip(value)
                self.table.setItem(row, column, cell)
        layout.addWidget(self.table, 3)
        self.output = QPlainTextEdit(self)
        self.output.setReadOnly(True)
        self.output.setAccessibleName("Tag writing progress")
        layout.addWidget(self.output, 2)
        self.summary = QLabel(f"{len(songs)} songs to write.", self)
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)
        self.progress = QProgressBar(self)
        self.progress.setRange(0, len(songs))
        self.progress.setValue(0)
        layout.addWidget(self.progress)
        buttons = QHBoxLayout()
        buttons.addStretch()
        self.close_button = QPushButton("Close", self)
        self.close_button.clicked.connect(self.reject)
        self.write_button = QPushButton("Write tags", self)
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
            cell.setText("Pending")
        self.progress.setRange(0, 0)
        self.summary.setText("Preparing write…")
        self.write_requested.emit()

    def set_busy(self, busy: bool) -> None:
        self._busy = busy
        self.write_button.setEnabled(bool(self.file_ids) and not busy and not self._completed)

    def set_progress(self, progress: TagWriteProgress) -> None:
        names = {
            "preview": "Preparing songs",
            "cover_discovery": "Finding covers",
            "reading": "Reading tags",
            "checking": "Checking file",
            "backup": "Creating backup",
            "writing": "Writing and verifying",
            "nfo_reading": "Checking album.nfo",
            "nfo_writing": "Updating album.nfo",
            "finished": "Writing complete",
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
        self.summary.setText("Could not complete writing.")
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
                    self.output.appendPlainText(f"Source image: {item.cover_path}")
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
                self.output.appendPlainText(f"Backup: {nfo.backup_path}")
        written = sum(item.state in ("confirmed", "catalog_pending") for item in report.results)
        self.summary.setText(
            f"{'Writing cancelled' if report.cancelled else 'Writing complete'} · "
            f"{written} files written."
            + (
                f" {sum(n.state == 'updated' for n in report.nfo_results)} NFO files updated."
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
        popup.setWindowTitle("Tag writing error")
        popup.setIcon(QMessageBox.Icon.Warning)
        popup.setText("The operation ended with errors.")
        popup.setInformativeText("You can save a report with errors and backup paths.")
        popup.setDetailedText(report_text(self._report) if self._report else self._error_message)
        save = popup.addButton("Save report…", QMessageBox.ButtonRole.ActionRole)
        popup.addButton("Close", QMessageBox.ButtonRole.RejectRole)
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
        dialog = QFileDialog(self, "Save write report", str(Path.home() / "tag-writing.json"))
        dialog.setOption(QFileDialog.Option.DontUseNativeDialog, True)
        dialog.setAcceptMode(QFileDialog.AcceptMode.AcceptSave)
        dialog.setDefaultSuffix("json")
        dialog.setNameFilter("JSON report (*.json)")
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
                self.set_error(f"Could not save the report: {exc}", offer_report=False)
        dialog.deleteLater()

    def reject(self) -> None:
        if self._busy:
            self._close_pending = True
            self.cancel_requested.emit()
            self.summary.setText("Closing… Waiting for the current file to finish.")
        else:
            super().reject()

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._busy:
            self.reject()
            event.ignore()
        else:
            super().closeEvent(event)
