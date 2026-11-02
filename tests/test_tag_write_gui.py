"""Real Qt workers preview, publish, cancel and reconcile temporary audio writes."""
# ruff: noqa: E402

import json
import threading

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import Qt, QTimer
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QFileDialog
from test_catalog_edit import edit
from test_import_gui_integration import wait_until
from test_tag_write import make_source
from test_tag_write import setup_tags as setup_tags

from trackfolio.application.write_tags import TagWriteService, WriteTagWrites
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


def open_preview(app, window, controller):
    QTest.mouseClick(window.write_tags_button, Qt.MouseButton.LeftButton)
    dialog = controller._tag_dialog
    assert dialog is not None
    assert not dialog.write_button.isEnabled()
    assert not window.table.isEnabled()
    dialog.fields["title"].setChecked(True)
    QTest.mouseClick(dialog.preview_button, Qt.MouseButton.LeftButton)
    wait_until(app, lambda: dialog._preview is not None and not controller._tag_running)
    return dialog


def test_gui_preview_selection_write_and_export_report(qt_app, setup_tags, tmp_path):
    database, repository, _, _, files = setup_tags
    sources = tuple(make_source(tmp_path, kind) for kind in ("flac", "mp3"))
    entries = tuple(
        repository.save(read_metadata(source), source.parent, source.name) for source in sources
    )
    for index, entry in enumerate(entries):
        edit(database, entry.file_id, title=f"Corrected {index}")
    originals = tuple(source.read_bytes() for source in sources)
    window, controller = open_window(qt_app, setup_tags, entries[0])
    try:
        window.select_files(tuple(entry.file_id for entry in entries))
        wait_until(qt_app, lambda: not controller._jobs)
        dialog = open_preview(qt_app, window, controller)
        assert all(item.state == "ready" for item in dialog._preview.items)
        assert tuple(source.read_bytes() for source in sources) == originals
        assert not files.journal_root.exists()
        dialog.table.item(1, 0).setCheckState(Qt.CheckState.Unchecked)
        reports = []
        controller.tag_write_finished.connect(reports.append)
        QTest.mouseClick(dialog.write_button, Qt.MouseButton.LeftButton)
        wait_until(qt_app, lambda: len(reports) == 1 and not controller._tag_running)
        assert [item.state for item in reports[0].results] == ["confirmed", "excluded"]
        assert read_metadata(sources[0]).title == "Corrected 0"
        assert sources[1].read_bytes() == originals[1]
        assert "Respaldo:" in dialog.details.toPlainText()
        destination = tmp_path / "write-report.json"

        def choose_report():
            picker = dialog.findChildren(QFileDialog)[-1]
            picker.selectFile(str(destination))
            picker.accept()

        QTimer.singleShot(0, choose_report)
        QTest.mouseClick(dialog.export_button, Qt.MouseButton.LeftButton)
        assert json.loads(destination.read_text())["operation_id"] == reports[0].operation_id
        dialog.reject()
        wait_until(qt_app, lambda: not controller._jobs)
        assert window.selected_file_ids() == tuple(entry.file_id for entry in entries)
    finally:
        teardown(window, controller)


def test_no_changes_or_changed_options_cannot_write(qt_app, setup_tags, tmp_path):
    database, repository, _, _, files = setup_tags
    source = make_source(tmp_path, "flac")
    entry = repository.save(read_metadata(source), source.parent, source.name)
    window, controller = open_window(qt_app, setup_tags, entry)
    try:
        dialog = open_preview(qt_app, window, controller)
        assert dialog._preview.items[0].state == "unchanged"
        assert not dialog.write_button.isEnabled()
        dialog.fields["album"].setChecked(True)
        assert not dialog._valid
        assert not files.journal_root.exists()
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
        dialog = open_preview(qt_app, window, controller)
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


def test_pending_operation_is_only_reconciled_after_explicit_review(
    qt_app, setup_tags, tmp_path, monkeypatch
):
    from test_tag_write import prepare_change

    source, entry, preview = prepare_change(setup_tags, tmp_path)
    _, _, catalog, codec, files = setup_tags
    confirm = catalog.confirm

    def unavailable(*args):
        raise OSError("database unavailable")

    monkeypatch.setattr(catalog, "confirm", unavailable)
    result = WriteTagWrites(catalog, codec, files).execute(preview, (entry.file_id,))
    assert result.results[0].state == "catalog_pending"
    monkeypatch.setattr(catalog, "confirm", confirm)
    written = source.read_bytes()
    window, controller = open_window(qt_app, setup_tags, entry)
    try:
        controller.check_tag_recovery()
        wait_until(qt_app, lambda: controller._recovery_dialog is not None)
        dialog = controller._recovery_dialog
        assert not window.table.isEnabled()
        assert not dialog.confirm_button.isEnabled()
        QTest.mouseClick(dialog.review_button, Qt.MouseButton.LeftButton)
        wait_until(qt_app, lambda: not controller._tag_running)
        assert dialog.confirm_button.isEnabled()
        assert source.read_bytes() == written and len(files.pending()) == 1
        QTest.mouseClick(dialog.confirm_button, Qt.MouseButton.LeftButton)
        wait_until(qt_app, lambda: not controller._tag_running)
        assert source.read_bytes() == written and files.pending() == ()
    finally:
        teardown(window, controller)


def test_startup_recovery_waits_for_active_catalogue_save(
    qt_app, setup_tags, tmp_path, monkeypatch
):
    from test_tag_write import prepare_change

    _, entry, preview = prepare_change(setup_tags, tmp_path)
    _, _, _, _, files = setup_tags
    files.journal(preview)
    window, controller = open_window(qt_app, setup_tags, entry)
    started, release = threading.Event(), threading.Event()
    open_writer = controller._edit_factory.open_writer

    def delayed(path):
        started.set()
        assert release.wait(5)
        return open_writer(path)

    monkeypatch.setattr(controller._edit_factory, "open_writer", delayed)
    try:
        QTest.mouseClick(window.edit_button, Qt.MouseButton.LeftButton)
        wait_until(qt_app, lambda: controller._edit_snapshot is not None and not controller._jobs)
        window.fields["title"].selectAll()
        QTest.keyClicks(window.fields["title"], "Saved before recovery")
        QTest.mouseClick(window.save_button, Qt.MouseButton.LeftButton)
        wait_until(qt_app, started.is_set)
        controller.check_tag_recovery()
        QTest.qWait(300)
        assert controller.saving and controller._recovery_dialog is None
        release.set()
        wait_until(qt_app, lambda: controller._recovery_dialog is not None)
        assert not controller.saving and not window.table.isEnabled()
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
        dialog = open_preview(qt_app, window, controller)
        reports = []
        controller.tag_write_finished.connect(reports.append)
        QTest.mouseClick(dialog.write_button, Qt.MouseButton.LeftButton)
        wait_until(qt_app, started.is_set)
        QTest.mouseClick(dialog.close_button, Qt.MouseButton.LeftButton)
        assert controller._tag_cancel.is_set()
        release.set()
        wait_until(qt_app, lambda: bool(reports) and not controller._tag_running)
        assert reports[0].cancelled and source.read_bytes() == original
        assert window.isVisible() and dialog.isVisible()
    finally:
        release.set()
        teardown(window, controller)
