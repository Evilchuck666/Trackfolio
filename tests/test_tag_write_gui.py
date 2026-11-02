"""Real Qt workers publish all saved differences and offer reports only on error."""
# ruff: noqa: E402

import json
import threading

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import Qt, QTimer
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QFileDialog, QPushButton
from test_catalog_edit import edit
from test_import_gui_integration import wait_until
from test_tag_write import make_source
from test_tag_write import setup_tags as setup_tags

from trackfolio.application.write_tags import TagWriteService
from trackfolio.infrastructure.catalog_edit import SqliteCatalogEditSessionFactory
from trackfolio.infrastructure.metadata import read_metadata
from trackfolio.infrastructure.session import open_catalog
from trackfolio.interfaces.gui.controller import CatalogController
from trackfolio.interfaces.gui.lifecycle import dispose_window
from trackfolio.interfaces.gui.window import MainWindow


def open_window(app, setup_tags, entry):
    database, _, catalog, codec, files = setup_tags
    window = MainWindow()
    controller = CatalogController(
        window,
        open_catalog,
        edit_factory=SqliteCatalogEditSessionFactory(),
        tag_writer=TagWriteService(catalog, codec, files),
    )
    window.show()
    controller.open_database(database)
    wait_until(app, lambda: window.current_file_id() == entry.file_id and not controller._jobs)
    return window, controller


def teardown(window, controller):
    controller.shutdown()
    dispose_window(window)


def open_dialog(app, window, controller):
    QTest.mouseClick(window.write_tags_button, Qt.MouseButton.LeftButton)
    dialog = controller._tag_dialog
    assert dialog is not None
    assert dialog.write_button.isEnabled()
    assert not window.table.isEnabled()
    assert dialog.table.rowCount() == len(window.selected_file_ids())
    assert {button.text() for button in dialog.findChildren(QPushButton)} == {
        "Cerrar",
        "Escribir etiquetas",
    }
    return dialog


def test_gui_lists_songs_immediately_and_writes_all_saved_fields(qt_app, setup_tags, tmp_path):
    database, repository, _, _, files = setup_tags
    sources = tuple(make_source(tmp_path, kind) for kind in ("flac", "mp3"))
    entries = tuple(
        repository.save(read_metadata(source), source.parent, source.name) for source in sources
    )
    for index, entry in enumerate(entries):
        edit(
            database,
            entry.file_id,
            title=f"Corrected {index}",
            album="New album",
            album_year=1981,
            artists=("One", "Two"),
            genres=("Rock",),
            track_number=3,
            track_total=12,
            disc_number=2,
            disc_total=3,
            lyrics=None,
        )
    originals = tuple(source.read_bytes() for source in sources)
    window, controller = open_window(qt_app, setup_tags, entries[0])
    try:
        window.select_files(tuple(entry.file_id for entry in entries))
        wait_until(qt_app, lambda: not controller._jobs)
        dialog = open_dialog(qt_app, window, controller)
        assert dialog.table.item(0, 0).text() == "Corrected 0"
        assert dialog.table.item(1, 0).text() == "Corrected 1"
        assert tuple(source.read_bytes() for source in sources) == originals
        assert not files.journal_root.exists()
        reports = []
        controller.tag_write_finished.connect(reports.append)
        QTest.mouseClick(dialog.write_button, Qt.MouseButton.LeftButton)
        wait_until(qt_app, lambda: len(reports) == 1 and not controller._tag_running)
        assert [item.state for item in reports[0].results] == ["confirmed", "confirmed"]
        for index, source in enumerate(sources):
            metadata = read_metadata(source)
            assert metadata.title == f"Corrected {index}"
            assert metadata.artists == ("One", "Two")
            assert metadata.album == "New album" and metadata.album_year == 1981
            assert metadata.track_number == 3 and metadata.track_total == 12
            assert metadata.disc_number == 2 and metadata.disc_total == 3
            assert metadata.genres == ("Rock",) and metadata.lyrics is None
            assert reports[0].results[index].backup_path is None
            assert not (source.parent / ".trackfolio-backups").exists()
        assert "Escribiendo y verificando" in dialog.output.toPlainText()
        assert dialog.table.rowCount() == 2 and dialog._error_popup is None
        assert not dialog.write_button.isEnabled()
        assert dialog.close_button.isEnabled()
        # A second click, including a programmatic request, cannot write again.
        repeated = QSignalSpy(dialog.write_requested)
        QTest.mouseClick(dialog.write_button, Qt.MouseButton.LeftButton)
        dialog._request_write()
        assert repeated.count() == 0 and len(reports) == 1
        dialog.reject()
        wait_until(qt_app, lambda: not controller._jobs)
        assert window.selected_file_ids() == tuple(entry.file_id for entry in entries)
    finally:
        teardown(window, controller)


def test_unchanged_songs_do_not_write_or_offer_a_report(qt_app, setup_tags, tmp_path):
    _, repository, _, _, files = setup_tags
    source = make_source(tmp_path, "flac")
    original = source.read_bytes()
    entry = repository.save(read_metadata(source), source.parent, source.name)
    window, controller = open_window(qt_app, setup_tags, entry)
    try:
        dialog = open_dialog(qt_app, window, controller)
        reports = []
        controller.tag_write_finished.connect(reports.append)
        QTest.mouseClick(dialog.write_button, Qt.MouseButton.LeftButton)
        wait_until(qt_app, lambda: bool(reports) and not controller._tag_running)
        assert reports[0].results[0].state == "unchanged"
        assert dialog.table.item(0, 3).text() == "Sin cambios"
        assert source.read_bytes() == original and not files.journal_root.exists()
        assert dialog._error_popup is None
        assert not dialog.write_button.isEnabled()
        assert dialog.close_button.isEnabled()
    finally:
        teardown(window, controller)


def test_errors_offer_export_in_popup_and_keep_successful_songs(qt_app, setup_tags, tmp_path):
    database, repository, _, _, _ = setup_tags
    sources = tuple(make_source(tmp_path, kind) for kind in ("flac", "mp3"))
    entries = tuple(
        repository.save(read_metadata(source), source.parent, source.name) for source in sources
    )
    for entry in entries:
        edit(database, entry.file_id, title="Saved correction")
    sources[1].unlink()
    window, controller = open_window(qt_app, setup_tags, entries[0])
    try:
        window.select_files(tuple(entry.file_id for entry in entries))
        wait_until(qt_app, lambda: not controller._jobs)
        dialog = open_dialog(qt_app, window, controller)
        QTest.mouseClick(dialog.write_button, Qt.MouseButton.LeftButton)
        wait_until(qt_app, lambda: dialog._error_popup is not None and not controller._tag_running)
        assert read_metadata(sources[0]).title == "Saved correction"
        assert dialog.table.rowCount() == 2
        assert "a.mp3" in dialog.output.toPlainText()
        destination = tmp_path / "write-report.json"

        def choose_report():
            picker = dialog.findChildren(QFileDialog)[-1]
            picker.selectFile(str(destination))
            picker.accept()

        popup = dialog._error_popup
        save = next(button for button in popup.buttons() if button.text() == "Guardar informe…")
        QTimer.singleShot(0, choose_report)
        QTest.mouseClick(save, Qt.MouseButton.LeftButton)
        stored = json.loads(destination.read_text())
        assert [item["state"] for item in stored["results"]] == ["confirmed", "excluded"]
        assert stored["results"][1]["message"]
        assert dialog.write_button.isEnabled()
        wait_until(qt_app, lambda: dialog._error_popup is None)
        # Repair the missing file and retry from the same dialog.
        make_source(tmp_path, "mp3")
        QTest.mouseClick(dialog.write_button, Qt.MouseButton.LeftButton)
        wait_until(qt_app, lambda: dialog._report is not None and not controller._tag_running)
        assert [item.state for item in dialog._report.results] == ["unchanged", "confirmed"]
        assert read_metadata(sources[1]).title == "Saved correction"
        assert not dialog.write_button.isEnabled()
        assert dialog.close_button.isEnabled()
    finally:
        teardown(window, controller)


def test_preparation_error_offers_a_report_without_touching_audio(
    qt_app, setup_tags, tmp_path, monkeypatch
):
    database, repository, catalog, _, files = setup_tags
    source = make_source(tmp_path, "flac")
    original = source.read_bytes()
    entry = repository.save(read_metadata(source), source.parent, source.name)
    edit(database, entry.file_id, title="Modified")

    def unavailable(_database):
        raise OSError("Catalogue unavailable")

    monkeypatch.setattr(catalog, "prepare", unavailable)
    window, controller = open_window(qt_app, setup_tags, entry)
    try:
        dialog = open_dialog(qt_app, window, controller)
        QTest.mouseClick(dialog.write_button, Qt.MouseButton.LeftButton)
        wait_until(qt_app, lambda: dialog._error_popup is not None and not controller._tag_running)
        assert "Catalogue unavailable" in dialog.output.toPlainText()
        assert source.read_bytes() == original and not files.journal_root.exists()
        assert any(button.text() == "Guardar informe…" for button in dialog._error_popup.buttons())
        assert dialog.write_button.isEnabled()
    finally:
        teardown(window, controller)


def test_window_close_during_tag_write_cancels_cooperatively(
    qt_app, setup_tags, tmp_path, monkeypatch
):
    database, repository, _, codec, _ = setup_tags
    source = make_source(tmp_path, "flac")
    original = source.read_bytes()
    entry = repository.save(read_metadata(source), source.parent, source.name)
    edit(database, entry.file_id, title="Corrected")
    started, release = threading.Event(), threading.Event()
    write = codec.write_verified

    def delayed(*args):
        started.set()
        assert release.wait(5)
        return write(*args)

    monkeypatch.setattr(codec, "write_verified", delayed)
    window, controller = open_window(qt_app, setup_tags, entry)
    closed = QSignalSpy(window.closing)
    try:
        dialog = open_dialog(qt_app, window, controller)
        QTest.mouseClick(dialog.write_button, Qt.MouseButton.LeftButton)
        wait_until(qt_app, started.is_set)
        assert not window.close()
        assert closed.count() == 0 and window.isVisible()
        responsive = []
        QTimer.singleShot(0, lambda: responsive.append(True))
        wait_until(qt_app, lambda: bool(responsive))
        release.set()
        wait_until(qt_app, lambda: closed.count() == 1)
        assert controller._closed and source.read_bytes() == original
    finally:
        release.set()
        teardown(window, controller)


@pytest.mark.parametrize("answer", ["Cancel", "Discard", "Save"])
def test_write_action_resolves_unsaved_catalogue_draft(
    qt_app, setup_tags, tmp_path, monkeypatch, answer
):
    from PySide6.QtWidgets import QMessageBox

    database, repository, _, _, files = setup_tags
    source = make_source(tmp_path, "flac")
    original = source.read_bytes()
    entry = repository.save(read_metadata(source), source.parent, source.name)
    window, controller = open_window(qt_app, setup_tags, entry)
    monkeypatch.setattr(
        controller, "_confirm_unsaved", lambda: getattr(QMessageBox.StandardButton, answer)
    )
    try:
        QTest.mouseClick(window.edit_button, Qt.MouseButton.LeftButton)
        wait_until(qt_app, lambda: controller._edit_snapshot is not None and not controller._jobs)
        field = window.fields["title"]
        field.selectAll()
        QTest.keyClicks(field, "Unsaved title")
        QTest.mouseClick(window.write_tags_button, Qt.MouseButton.LeftButton)
        if answer == "Cancel":
            assert controller._tag_dialog is None and window.edit_dirty()
        else:
            wait_until(qt_app, lambda: controller._tag_dialog is not None)
        assert repository.get(entry.file_id).metadata.title == (
            "Unsaved title" if answer == "Save" else "Original"
        )
        assert source.read_bytes() == original and not files.journal_root.exists()
    finally:
        teardown(window, controller)


def test_cancel_button_uses_the_current_operation_cancellation(
    qt_app, setup_tags, tmp_path, monkeypatch
):
    database, repository, _, codec, _ = setup_tags
    source = make_source(tmp_path, "flac")
    original = source.read_bytes()
    entry = repository.save(read_metadata(source), source.parent, source.name)
    edit(database, entry.file_id, title="Corrected")
    started, release = threading.Event(), threading.Event()
    write = codec.write_verified

    def delayed(*args):
        started.set()
        assert release.wait(5)
        return write(*args)

    monkeypatch.setattr(codec, "write_verified", delayed)
    window, controller = open_window(qt_app, setup_tags, entry)
    try:
        dialog = open_dialog(qt_app, window, controller)
        reports = []
        controller.tag_write_finished.connect(reports.append)
        QTest.mouseClick(dialog.write_button, Qt.MouseButton.LeftButton)
        wait_until(qt_app, started.is_set)
        QTest.mouseClick(dialog.close_button, Qt.MouseButton.LeftButton)
        assert controller._tag_cancel.is_set()
        release.set()
        wait_until(qt_app, lambda: bool(reports) and not controller._tag_running)
        assert reports[0].cancelled and source.read_bytes() == original
        assert window.isVisible() and controller._tag_dialog is None
    finally:
        release.set()
        teardown(window, controller)
