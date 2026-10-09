"""Collect import intentions and render progress using Qt-independent import values."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)

from trackfolio.application.import_catalog import ImportProgress, ImportReport, ImportRequest
from trackfolio.interfaces.gui.theme import icon


def _label(text: str, parent: QWidget, *, name: str = "MutedLabel") -> QLabel:
    result = QLabel(text, parent)
    result.setObjectName(name)
    result.setWordWrap(True)
    result.setTextFormat(Qt.TextFormat.PlainText)
    return result


def _picker_directory(path: Path) -> Path:
    """Use a real user directory when the suggested data folder does not exist yet."""
    expanded = path.expanduser()
    for directory in (expanded, *expanded.parents):
        if directory.is_dir():
            return directory
    return Path.home()


class ImportDialog(QDialog):
    """Validate form completeness; filesystem validation belongs to the use case."""

    def __init__(
        self,
        parent: QWidget | None,
        current_catalog: Path | None,
        initial_directory: Path,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Importar música")
        self.setWindowIcon(icon("import"))
        self.setModal(True)
        self.setMinimumWidth(600)
        self._current_catalog = current_catalog
        self._initial_directory = initial_directory
        self._request: ImportRequest | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(18)
        layout.addWidget(_label("Importar música", self, name="PageTitle"))
        root_group = QGroupBox("Carpeta de música", self)
        root_layout = QVBoxLayout(root_group)
        root_row = QHBoxLayout()
        self.root_edit = QLineEdit(root_group)
        self.root_edit.setAccessibleName("Carpeta de música")
        self.root_edit.setPlaceholderText("Selecciona la carpeta que contiene tu música")
        self.folder_button = QPushButton(icon("open"), "Elegir carpeta…", root_group)
        self.folder_button.clicked.connect(self._choose_root)
        root_row.addWidget(self.root_edit, 1)
        root_row.addWidget(self.folder_button)
        root_layout.addLayout(root_row)
        root_layout.addWidget(
            _label("Se incluyen las subcarpetas y los archivos FLAC y MP3.", self)
        )
        layout.addWidget(root_group)

        destination_group = QGroupBox("Destino", self)
        destination_layout = QVBoxLayout(destination_group)
        destination_layout.setSpacing(12)
        self.update_radio = QRadioButton("Usar el catálogo abierto", destination_group)
        self.update_radio.setEnabled(current_catalog is not None)
        destination_layout.addWidget(self.update_radio)
        self.current_label = _label(
            str(current_catalog) if current_catalog is not None else "No hay un catálogo abierto.",
            destination_group,
        )
        self.current_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        destination_layout.addWidget(self.current_label)
        self.update_note = _label(
            "Se añadirán canciones nuevas y se actualizarán las ya importadas desde esta carpeta.",
            destination_group,
        )
        destination_layout.addWidget(self.update_note)
        self.create_radio = QRadioButton("Crear un catálogo nuevo", destination_group)
        destination_layout.addWidget(self.create_radio)
        destination_row = QHBoxLayout()
        self.destination_edit = QLineEdit(destination_group)
        self.destination_edit.setAccessibleName("Archivo del catálogo nuevo")
        self.destination_edit.setText(str(initial_directory / "Mi música.tfo"))
        self.destination_edit.setCursorPosition(0)
        self.destination_button = QPushButton("Elegir archivo…", destination_group)
        self.destination_button.clicked.connect(self._choose_destination)
        destination_row.addWidget(self.destination_edit, 1)
        destination_row.addWidget(self.destination_button)
        destination_layout.addLayout(destination_row)
        self.create_note = _label(
            "Elige un archivo nuevo. Los catálogos existentes no se sobrescriben.",
            destination_group,
        )
        destination_layout.addWidget(self.create_note)
        layout.addWidget(destination_group)
        self.error_label = _label("", self, name="ErrorMessage")
        self.error_label.hide()
        layout.addWidget(self.error_label)

        actions = QHBoxLayout()
        actions.addStretch()
        self.cancel_button = QPushButton("Cancelar", self)
        self.cancel_button.clicked.connect(self.reject)
        self.import_button = QPushButton(icon("import"), "Importar", self)
        self.import_button.setObjectName("PrimaryButton")
        self.import_button.setDefault(True)
        self.import_button.clicked.connect(self.accept)
        actions.addWidget(self.cancel_button)
        actions.addWidget(self.import_button)
        layout.addLayout(actions)

        self.create_radio.toggled.connect(self._update_mode)
        self.root_edit.textChanged.connect(self._update_form)
        self.destination_edit.textChanged.connect(self._update_form)
        self.root_edit.textChanged.connect(self.root_edit.setToolTip)
        self.destination_edit.textChanged.connect(self.destination_edit.setToolTip)
        self.destination_edit.setToolTip(self.destination_edit.text())
        self.update_radio.setChecked(current_catalog is not None)
        self.create_radio.setChecked(current_catalog is None)
        self._update_mode()

    def _update_mode(self) -> None:
        creating = self.create_radio.isChecked()
        self.destination_edit.setEnabled(creating)
        self.destination_button.setEnabled(creating)
        self.create_note.setVisible(creating)
        self.update_note.setVisible(not creating)
        self._update_form()

    def _update_form(self) -> None:
        has_root = bool(self.root_edit.text().strip())
        has_destination = (
            bool(self.destination_edit.text().strip())
            if self.create_radio.isChecked()
            else self._current_catalog is not None
        )
        self.import_button.setEnabled(has_root and has_destination)
        self.error_label.hide()

    def _choose_root(self) -> None:
        dialog = QFileDialog(self, "Elegir carpeta de música")
        dialog.setOption(QFileDialog.Option.DontUseNativeDialog, True)
        dialog.setOption(QFileDialog.Option.ShowDirsOnly, True)
        dialog.setFileMode(QFileDialog.FileMode.Directory)
        suggested = Path(self.root_edit.text().strip() or self._initial_directory)
        dialog.setDirectory(str(_picker_directory(suggested)))
        if dialog.exec() == QDialog.DialogCode.Accepted:
            selected = dialog.selectedFiles()
            if selected:
                self.root_edit.setText(selected[0])
                self.root_edit.setCursorPosition(0)

    def _choose_destination(self) -> None:
        dialog = QFileDialog(self, "Crear catálogo de Trackfolio")
        dialog.setOption(QFileDialog.Option.DontUseNativeDialog, True)
        dialog.setOption(QFileDialog.Option.DontConfirmOverwrite, True)
        dialog.setAcceptMode(QFileDialog.AcceptMode.AcceptSave)
        dialog.setFileMode(QFileDialog.FileMode.AnyFile)
        dialog.setNameFilter("Catálogos de Trackfolio (*.tfo)")
        dialog.setDefaultSuffix("tfo")
        destination = Path(self.destination_edit.text().strip())
        dialog.setDirectory(
            str(
                _picker_directory(
                    destination.parent if destination.name else self._initial_directory
                )
            )
        )
        dialog.selectFile(destination.name or "Mi música.tfo")
        if dialog.exec() == QDialog.DialogCode.Accepted:
            selected = dialog.selectedFiles()
            if selected:
                self.destination_edit.setText(selected[0])
                self.destination_edit.setCursorPosition(0)

    def accept(self) -> None:
        root = self.root_edit.text().strip()
        destination = self.destination_edit.text().strip()
        message = ""
        if not root:
            message = "Selecciona una carpeta de música."
        elif self.create_radio.isChecked() and not destination:
            message = "Selecciona el archivo del catálogo nuevo."
        elif self.update_radio.isChecked() and self._current_catalog is None:
            message = "Abre un catálogo o elige crear uno nuevo."
        if message:
            self.error_label.setText(message)
            self.error_label.show()
            return
        if self.create_radio.isChecked():
            path = Path(destination).expanduser()
            if not path.suffix:
                path = path.with_suffix(".tfo")
            self._request = ImportRequest(Path(root).expanduser(), path, "create")
        else:
            assert self._current_catalog is not None
            self._request = ImportRequest(Path(root).expanduser(), self._current_catalog, "update")
        super().accept()

    def reject(self) -> None:
        self._request = None
        super().reject()

    def request(self) -> ImportRequest | None:
        return self._request


class ImportProgressDialog(QDialog):
    """Keep cancellation accessible until the worker returns its final report."""

    cancel_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Importación de música")
        self.setWindowIcon(icon("import"))
        self.setMinimumWidth(580)
        self._active = True
        self._cancelling = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)
        self.phase_label = _label("Preparando importación…", self, name="PageTitle")
        layout.addWidget(self.phase_label)
        self.progress_bar = QProgressBar(self)
        self.progress_bar.setAccessibleName("Progreso de importación")
        self.progress_bar.setRange(0, 0)
        layout.addWidget(self.progress_bar)
        self.current_label = _label("", self)
        self.current_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.current_label)
        self.counts_label = _label("Encontrados: 0", self)
        layout.addWidget(self.counts_label)
        self.note_label = _label("Cancelar conserva las canciones que ya se hayan guardado.", self)
        layout.addWidget(self.note_label)
        self.error_label = _label("", self, name="ErrorMessage")
        self.error_label.hide()
        layout.addWidget(self.error_label)
        self.issues_label = _label("Incidencias", self, name="SectionTitle")
        self.issues_label.hide()
        layout.addWidget(self.issues_label)
        self.issues = QPlainTextEdit(self)
        self.issues.setAccessibleName("Incidencias de importación")
        self.issues.setReadOnly(True)
        self.issues.setMinimumHeight(150)
        self.issues.hide()
        layout.addWidget(self.issues, 1)
        actions = QHBoxLayout()
        actions.addStretch()
        self.action_button = QPushButton("Cancelar", self)
        self.action_button.clicked.connect(self._activate_button)
        actions.addWidget(self.action_button)
        layout.addLayout(actions)

    def set_progress(self, progress: ImportProgress) -> None:
        if not self._active:
            return
        if not self._cancelling:
            self.phase_label.setText(
                {
                    "preparing": "Preparando importación…",
                    "scanning": "Explorando carpeta…",
                    "importing": "Importando música…",
                    "finalizing": "Finalizando importación…",
                }[progress.phase]
            )
        if progress.total is None:
            self.progress_bar.setRange(0, 0)
        else:
            self.progress_bar.setRange(0, max(1, progress.total))
            self.progress_bar.setValue(progress.processed)
            self.progress_bar.setFormat(f"{progress.processed} / {progress.total}")
        self.current_label.setText(str(progress.current_path) if progress.current_path else "")
        self.counts_label.setText(
            f"Encontrados: {progress.discovered} · Nuevos: {progress.created} · "
            f"Actualizados: {progress.updated} · Fallidos: {progress.failed}"
        )

    def set_cancelling(self) -> None:
        if not self._active:
            return
        self._cancelling = True
        self.phase_label.setText("Cancelando…")
        self.note_label.setText(
            "Esperando a que termine el archivo actual y se cierre el catálogo."
        )
        self.action_button.setText("Cancelando…")
        self.action_button.setEnabled(False)

    def set_report(self, report: ImportReport) -> None:
        self._active = False
        self._cancelling = False
        title = {
            "completed": "Importación completada",
            "cancelled": "Importación cancelada",
            "failed": "No se pudo completar la importación",
        }[report.state]
        if report.state == "completed" and report.issues:
            title += " con incidencias"
        self.phase_label.setText(title)
        self.progress_bar.setRange(0, max(1, report.total or report.processed))
        self.progress_bar.setValue(report.processed)
        total = str(report.total) if report.total is not None else "total desconocido"
        self.progress_bar.setFormat(f"{report.processed} / {total}")
        destination = "Catálogo" if report.saved else "Destino solicitado"
        self.current_label.setText(f"{destination}: {report.database_path}")
        pending = str(report.pending) if report.pending is not None else "total desconocido"
        self.counts_label.setText(
            f"Nuevos: {report.created} · Actualizados: {report.updated} · "
            f"Fallidos: {report.failed} · Pendientes: {pending}"
        )
        if report.total is None:
            self.counts_label.setText(
                f"Encontrados: {report.discovered}\n{self.counts_label.text()}"
            )
        if report.saved:
            noun = "canción" if report.saved == 1 else "canciones"
            saved = "Se ha guardado" if report.saved == 1 else "Se han guardado"
            retained = "se conserva" if report.saved == 1 else "se conservan"
            adjective = "guardada" if report.saved == 1 else "guardadas"
            self.note_label.setText(
                f"{saved} {report.saved} {noun}."
                if report.state == "completed"
                else f"Resultado parcial: {retained} {report.saved} {noun} {adjective}."
            )
        elif report.state == "completed" and report.total == 0:
            self.note_label.setText(
                "No se encontraron archivos FLAC o MP3. No se creó un catálogo."
            )
        else:
            self.note_label.setText("No se guardaron canciones.")
        self.error_label.setText(report.fatal_error or "")
        self.error_label.setVisible(bool(report.fatal_error))
        stages = {
            "scan": "Exploración",
            "read": "Lectura",
            "write": "Guardado",
            "cleanup": "Limpieza",
        }
        self.issues.setPlainText(
            "\n\n".join(
                f"{stages[issue.stage]} · {issue.path}\n{issue.message}" for issue in report.issues
            )
        )
        self.issues_label.setVisible(bool(report.issues))
        self.issues.setVisible(bool(report.issues))
        self.action_button.setText("Cerrar")
        self.action_button.setEnabled(True)
        self.action_button.setDefault(True)

    def _activate_button(self) -> None:
        if self._active:
            self._request_cancel()
        else:
            self.accept()

    def _request_cancel(self) -> None:
        if self._active and not self._cancelling:
            self.set_cancelling()
            self.cancel_requested.emit()

    def accept(self) -> None:
        if self._active:
            self._request_cancel()
        else:
            super().accept()

    def reject(self) -> None:
        if self._active:
            self._request_cancel()
        else:
            super().reject()

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._active:
            self._request_cancel()
            event.ignore()
        else:
            super().closeEvent(event)
