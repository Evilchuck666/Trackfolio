"""Import forms and cancellation states exercised through the real Qt widgets."""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QCoreApplication, QEvent, QPoint, Qt, QTimer  # noqa: E402
from PySide6.QtTest import QSignalSpy, QTest  # noqa: E402
from PySide6.QtWidgets import QDialog, QFileDialog  # noqa: E402

from trackfolio.application.import_catalog import (  # noqa: E402
    ImportIssue,
    ImportProgress,
    ImportReport,
    ImportRequest,
)
from trackfolio.domain.catalog import CatalogSummary  # noqa: E402
from trackfolio.interfaces.gui.import_dialog import (  # noqa: E402
    ImportDialog,
    ImportProgressDialog,
)
from trackfolio.interfaces.gui.window import MainWindow  # noqa: E402


def dispose(widget, app):
    widget.close()
    widget.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()


@pytest.fixture
def import_dialog(qt_app, tmp_path):
    dialog = ImportDialog(None, None, tmp_path)
    dialog.show()
    qt_app.processEvents()
    yield dialog
    dispose(dialog, qt_app)


@pytest.fixture
def progress_dialog(qt_app, tmp_path):
    dialog = ImportProgressDialog()
    dialog.show()
    qt_app.processEvents()
    yield dialog
    dialog.set_report(ImportReport(tmp_path / "result.tfo", "completed", 0, 0, 0, 0, 0, ()))
    dispose(dialog, qt_app)


@pytest.fixture
def main_window(qt_app):
    window = MainWindow()
    window.show()
    qt_app.processEvents()
    yield window
    window.close_guard = None
    dispose(window, qt_app)


def test_new_catalog_form_collects_request_without_creating_files(import_dialog, tmp_path):
    root = tmp_path / "Música Ω"
    root.mkdir()
    destination = tmp_path / "Mi catálogo"
    assert import_dialog.create_radio.isChecked()
    assert not import_dialog.update_radio.isEnabled()
    assert not import_dialog.import_button.isEnabled()
    import_dialog.root_edit.setText(str(root))
    import_dialog.destination_edit.setText(str(destination))
    assert import_dialog.import_button.isEnabled()
    QTest.mouseClick(import_dialog.import_button, Qt.MouseButton.LeftButton)
    assert import_dialog.result() == QDialog.DialogCode.Accepted
    assert import_dialog.request() == ImportRequest(root, destination.with_suffix(".tfo"), "create")
    assert not destination.with_suffix(".tfo").exists()


def test_current_catalog_defaults_to_update_and_can_switch_to_create(qt_app, tmp_path):
    catalog = tmp_path / "legacy.sqlite3"
    dialog = ImportDialog(None, catalog, tmp_path)
    dialog.show()
    qt_app.processEvents()
    try:
        assert dialog.update_radio.isChecked()
        assert not dialog.destination_edit.isEnabled()
        assert not dialog.destination_button.isEnabled()
        assert "actualizarán" in dialog.update_note.text()
        dialog.root_edit.setText(str(tmp_path / "music"))
        QTest.mouseClick(dialog.create_radio, Qt.MouseButton.LeftButton, pos=QPoint(8, 8))
        assert dialog.create_radio.isChecked()
        assert dialog.destination_edit.isEnabled()
        QTest.mouseClick(dialog.update_radio, Qt.MouseButton.LeftButton, pos=QPoint(8, 8))
        QTest.mouseClick(dialog.import_button, Qt.MouseButton.LeftButton)
        assert dialog.request() == ImportRequest(tmp_path / "music", catalog, "update")
        assert not catalog.exists()
    finally:
        dispose(dialog, qt_app)


def test_form_validates_missing_values_without_accepting(import_dialog):
    accepted = QSignalSpy(import_dialog.accepted)
    import_dialog.accept()
    assert accepted.count() == 0
    assert "carpeta" in import_dialog.error_label.text()
    import_dialog.root_edit.setText("music")
    import_dialog.destination_edit.clear()
    assert not import_dialog.import_button.isEnabled()
    import_dialog.accept()
    assert accepted.count() == 0
    assert "archivo" in import_dialog.error_label.text()
    assert import_dialog.request() is None


def test_qt_folder_and_destination_pickers_select_unicode_paths(import_dialog, tmp_path):
    root = tmp_path / "Música y espacios Ω"
    root.mkdir()
    destination = tmp_path / "Catálogo Ω.tfo"
    pickers = []

    def choose_root():
        chooser = import_dialog.findChildren(QFileDialog)[-1]
        pickers.append(chooser.testOption(QFileDialog.Option.DontUseNativeDialog))
        assert chooser.fileMode() == QFileDialog.FileMode.Directory
        chooser.setDirectory(str(tmp_path))
        chooser.selectFile(str(root))
        chooser.accept()

    QTimer.singleShot(0, choose_root)
    QTest.mouseClick(import_dialog.folder_button, Qt.MouseButton.LeftButton)
    assert Path(import_dialog.root_edit.text()) == root

    def choose_destination():
        chooser = import_dialog.findChildren(QFileDialog)[-1]
        pickers.append(chooser.testOption(QFileDialog.Option.DontUseNativeDialog))
        assert chooser.acceptMode() == QFileDialog.AcceptMode.AcceptSave
        assert chooser.defaultSuffix() == "tfo"
        chooser.selectFile(str(destination))
        chooser.accept()

    QTimer.singleShot(0, choose_destination)
    QTest.mouseClick(import_dialog.destination_button, Qt.MouseButton.LeftButton)
    assert Path(import_dialog.destination_edit.text()) == destination
    assert pickers == [True, True]
    assert not destination.exists()


def test_cancelled_pickers_and_form_leave_fields_and_files_untouched(import_dialog, tmp_path):
    initial_destination = import_dialog.destination_edit.text()

    def cancel_picker():
        import_dialog.findChildren(QFileDialog)[-1].reject()

    QTimer.singleShot(0, cancel_picker)
    QTest.mouseClick(import_dialog.folder_button, Qt.MouseButton.LeftButton)
    assert import_dialog.root_edit.text() == ""
    QTimer.singleShot(0, cancel_picker)
    QTest.mouseClick(import_dialog.destination_button, Qt.MouseButton.LeftButton)
    assert import_dialog.destination_edit.text() == initial_destination
    import_dialog.root_edit.setText(str(tmp_path))
    QTest.mouseClick(import_dialog.cancel_button, Qt.MouseButton.LeftButton)
    assert import_dialog.result() == QDialog.DialogCode.Rejected
    assert import_dialog.request() is None
    assert not Path(initial_destination).exists()


def test_missing_data_directory_uses_existing_parent_in_picker(qt_app, tmp_path):
    suggested = tmp_path / "not-created" / "Trackfolio"
    dialog = ImportDialog(None, None, suggested)
    dialog.show()
    qt_app.processEvents()
    directory = []

    def cancel_picker():
        chooser = dialog.findChildren(QFileDialog)[-1]
        directory.append(Path(chooser.directory().absolutePath()))
        chooser.reject()

    try:
        QTimer.singleShot(0, cancel_picker)
        QTest.mouseClick(dialog.folder_button, Qt.MouseButton.LeftButton)
        QTimer.singleShot(0, cancel_picker)
        QTest.mouseClick(dialog.destination_button, Qt.MouseButton.LeftButton)
        assert directory == [tmp_path, tmp_path]
        assert dialog.destination_edit.text() == str(suggested / "Mi música.tfo")
        assert not suggested.exists()
    finally:
        dispose(dialog, qt_app)


def test_progress_switches_from_scan_to_exact_counts(progress_dialog, tmp_path):
    progress_dialog.set_progress(ImportProgress("scanning", 7, None, 0, 0, 0))
    assert progress_dialog.progress_bar.minimum() == progress_dialog.progress_bar.maximum() == 0
    assert "Explorando" in progress_dialog.phase_label.text()
    assert "Encontrados: 7" in progress_dialog.counts_label.text()
    path = tmp_path / "<artista>" / "Música.flac"
    progress_dialog.set_progress(ImportProgress("importing", 7, 7, 2, 1, 1, path))
    assert progress_dialog.progress_bar.maximum() == 7
    assert progress_dialog.progress_bar.value() == 4
    assert progress_dialog.progress_bar.format() == "4 / 7"
    assert progress_dialog.current_label.text() == str(path)
    assert progress_dialog.current_label.textFormat() == Qt.TextFormat.PlainText
    assert "Nuevos: 2" in progress_dialog.counts_label.text()


@pytest.mark.parametrize("action", ["button", "close", "escape"])
def test_cancel_keeps_progress_alive_and_is_requested_once(progress_dialog, action):
    cancelled = QSignalSpy(progress_dialog.cancel_requested)
    if action == "button":
        QTest.mouseClick(progress_dialog.action_button, Qt.MouseButton.LeftButton)
    elif action == "close":
        assert not progress_dialog.close()
    else:
        QTest.keyClick(progress_dialog, Qt.Key.Key_Escape)
    assert cancelled.count() == 1
    assert progress_dialog.isVisible()
    assert progress_dialog.phase_label.text() == "Cancelando…"
    assert not progress_dialog.action_button.isEnabled()
    progress_dialog.set_progress(ImportProgress("finalizing", 4, 4, 2, 0, 0))
    assert progress_dialog.phase_label.text() == "Cancelando…"
    progress_dialog.close()
    assert cancelled.count() == 1


def test_partial_report_shows_preserved_commits_pending_and_plain_incidents(
    progress_dialog, tmp_path
):
    progress_dialog.set_report(
        ImportReport(
            tmp_path / "result.tfo",
            "cancelled",
            10,
            10,
            2,
            1,
            1,
            (ImportIssue(tmp_path / "<broken>.mp3", "read", "No se pudo leer <archivo>."),),
        )
    )
    assert "cancelada" in progress_dialog.phase_label.text()
    assert "se conservan 3" in progress_dialog.note_label.text()
    assert "Pendientes: 6" in progress_dialog.counts_label.text()
    assert progress_dialog.issues.isVisible() and progress_dialog.issues.isReadOnly()
    assert "<broken>.mp3" in progress_dialog.issues.toPlainText()
    assert "No se pudo leer <archivo>." in progress_dialog.issues.toPlainText()
    assert progress_dialog.action_button.text() == "Cerrar"
    assert progress_dialog.action_button.isEnabled()
    QTest.mouseClick(progress_dialog.action_button, Qt.MouseButton.LeftButton)
    assert not progress_dialog.isVisible()


def test_failed_report_and_cancelled_scan_display_unknown_total(progress_dialog, tmp_path):
    progress_dialog.set_report(
        ImportReport(
            tmp_path / "result.tfo", "failed", 2, None, 0, 0, 0, (), "El destino no es compatible."
        )
    )
    assert progress_dialog.error_label.text() == "El destino no es compatible."
    assert progress_dialog.error_label.isVisible()
    assert "Pendientes: total desconocido" in progress_dialog.counts_label.text()
    assert "Encontrados: 2" in progress_dialog.counts_label.text()
    assert progress_dialog.current_label.text().startswith("Destino solicitado:")
    assert progress_dialog.progress_bar.maximum() == 1
    progress_dialog.set_report(
        ImportReport(tmp_path / "result.tfo", "cancelled", 2, None, 0, 0, 0, ())
    )
    assert progress_dialog.error_label.isHidden()
    assert progress_dialog.issues.isHidden()
    assert progress_dialog.note_label.text() == "No se guardaron canciones."


def test_empty_and_completed_with_incidents_are_presented_as_completed(progress_dialog, tmp_path):
    progress_dialog.set_report(
        ImportReport(tmp_path / "result.tfo", "completed", 0, 0, 0, 0, 0, ())
    )
    assert "No se encontraron archivos FLAC o MP3" in progress_dialog.note_label.text()
    progress_dialog.set_report(
        ImportReport(
            tmp_path / "result.tfo",
            "completed",
            1,
            1,
            1,
            0,
            0,
            (ImportIssue(tmp_path / "inaccessible", "scan", "Carpeta inaccesible."),),
        )
    )
    assert progress_dialog.phase_label.text() == "Importación completada con incidencias"
    assert progress_dialog.note_label.text() == "Se ha guardado 1 canción."
    assert "Exploración" in progress_dialog.issues.toPlainText()


def test_import_available_without_catalog_and_import_state_overrides_query_busy(main_window):
    imported = QSignalSpy(main_window.import_requested)
    assert main_window.import_button.isEnabled()
    assert main_window.import_action.isEnabled()
    QTest.mouseClick(main_window.import_button, Qt.MouseButton.LeftButton)
    assert imported.count() == 1
    main_window.set_catalog(
        Path("result.tfo"), (CatalogSummary(1, 2, "Song", (), None, None, "song.flac"),)
    )
    main_window.set_importing(True)
    assert not main_window.open_button.isEnabled()
    assert not main_window.import_button.isEnabled()
    assert not main_window.import_action.isEnabled()
    assert not main_window.refresh_button.isEnabled()
    assert not main_window.table.isEnabled()
    main_window.set_busy(False)
    assert not main_window.refresh_button.isEnabled()
    main_window.set_importing(False)
    assert main_window.open_button.isEnabled()
    assert main_window.import_button.isEnabled()
    assert main_window.refresh_button.isEnabled()
    assert main_window.table.isEnabled()


def test_main_window_close_guard_defers_closing_signal(main_window):
    closed = QSignalSpy(main_window.closing)
    main_window.close_guard = lambda: False
    assert not main_window.close()
    assert main_window.isVisible()
    assert closed.count() == 0
    main_window.close_guard = lambda: True
    assert main_window.close()
    assert closed.count() == 1
