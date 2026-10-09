"""Exercise the catalog editor with real Qt widgets and complete ordered names."""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QCoreApplication, QEvent, Qt  # noqa: E402
from PySide6.QtGui import QKeySequence  # noqa: E402
from PySide6.QtTest import QSignalSpy, QTest  # noqa: E402

from trackfolio.domain.catalog import CatalogEntry, CatalogSummary  # noqa: E402
from trackfolio.domain.catalog_edit import EditableValues  # noqa: E402
from trackfolio.domain.metadata import TrackMetadata  # noqa: E402
from trackfolio.interfaces.gui.import_dialog import ImportDialog  # noqa: E402
from trackfolio.interfaces.gui.ordered_labels import OrderedLabels  # noqa: E402
from trackfolio.interfaces.gui.window import MainWindow  # noqa: E402


@pytest.fixture
def window(qt_app):
    result = MainWindow()
    result.set_edit_enabled(True)
    result.show()
    qt_app.processEvents()
    yield result
    result.close()
    result.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    qt_app.processEvents()


def load_detail(window, metadata=None):
    metadata = metadata or TrackMetadata(title="Original", artists=("Abbath",))
    rows = tuple(
        CatalogSummary(file_id, file_id + 10, "Original", (), None, None, f"{file_id}.flac")
        for file_id in (1, 2)
    )
    window.set_catalog(Path("catalog.tfo"), rows)
    window.set_detail(CatalogEntry(1, 11, Path("unavailable"), "1.flac", metadata))
    return EditableValues.from_metadata(metadata)


def replace_text(field, text):
    field.setFocus()
    field.selectAll()
    if text:
        QTest.keyClicks(field, text)
    else:
        QTest.keyClick(field, Qt.Key.Key_Backspace)


def test_edit_actions_need_an_enabled_adapter_and_loaded_detail(window):
    assert not window.edit_button.isEnabled()
    values = load_detail(window)
    assert window.edit_button.isEnabled()
    window.set_edit_enabled(False)
    assert not window.edit_button.isEnabled()
    window.set_edit_enabled(True)
    window.set_busy(True)
    assert not window.edit_button.isEnabled()
    window.set_busy(False)
    window.begin_edit(values)
    assert not window.fields["title"].isReadOnly()
    assert not window.lyrics.isReadOnly()
    assert window.fields["artists"].isHidden()
    assert window.ordered_labels["artists"].isVisible()
    assert not window.save_button.isEnabled()
    assert window.cancel_edit_button.isEnabled()
    assert not window.edit_dirty()
    assert window.edit_status.text() == "Cambios en el catálogo"


def test_draft_has_only_user_changes_and_preserves_plain_text(window):
    values = load_detail(window, TrackMetadata(title="Original", lyrics="<b>Literal</b>\nSong"))
    dirty = QSignalSpy(window.dirty_changed)
    window.begin_edit(values)
    assert dirty.at(0) == [False]
    replace_text(window.fields["title"], "Updated")
    assert window.edit_patch().as_dict() == {"title": "Updated"}
    assert window.edit_dirty()
    assert window.save_button.isEnabled()
    assert dirty.at(1) == [True]
    assert "Cambios sin guardar" in window.edit_status.text()
    replace_text(window.fields["title"], "Original")
    assert window.edit_patch().empty
    assert not window.save_button.isEnabled()
    assert dirty.at(2) == [False]
    window.lyrics.setFocus()
    window.lyrics.selectAll()
    QTest.keyClicks(window.lyrics, "<b>Another literal</b>")
    assert window.edit_patch().as_dict() == {"lyrics": "<b>Another literal</b>"}
    assert window.lyrics.toPlainText() == "<b>Another literal</b>"


@pytest.mark.parametrize("invalid", ["0", "-2", "1.5", "year", "10000", "9" * 25])
def test_invalid_year_keeps_draft_and_disables_save(window, invalid):
    window.begin_edit(load_detail(window))
    replace_text(window.fields["album_year"], invalid)
    assert window.edit_dirty()
    assert not window.save_button.isEnabled()
    assert window.fields["album_year"].text() == invalid
    assert window.field_errors["album_year"].isVisible()
    replace_text(window.fields["album_year"], "1981")
    assert window.save_button.isEnabled()
    assert window.field_errors["album_year"].isHidden()
    assert window.edit_patch().as_dict() == {"album_year": 1981}


def test_number_total_validation_does_not_block_unrelated_edits(window):
    values = load_detail(window, TrackMetadata(title="Original", track_number=9, track_total=5))
    window.begin_edit(values)
    replace_text(window.fields["title"], "Updated")
    assert window.save_button.isEnabled()
    replace_text(window.fields["track_number"], "8")
    assert not window.save_button.isEnabled()
    assert window.field_errors["track_number"].isVisible()
    assert window.field_errors["track_total"].isVisible()
    replace_text(window.fields["track_total"], "10")
    assert window.save_button.isEnabled()
    replace_text(window.fields["track_total"], "")
    assert window.save_button.isEnabled()
    assert window.edit_patch().as_dict()["track_total"] is None


def test_ordered_labels_add_remove_and_move_complete_exact_names(qt_app):
    widget = OrderedLabels("Artista(s)")
    widget.show()
    try:
        widget.set_names(("Earth, Wind & Fire", "Heavy; Progressive"))
        changes = QSignalSpy(widget.changed)
        widget.name_edit.setText("  Björk Ω  ")
        QTest.mouseClick(widget.add_button, Qt.MouseButton.LeftButton)
        assert widget.names() == ("Earth, Wind & Fire", "Heavy; Progressive", "  Björk Ω  ")
        widget.name_edit.setText("  Björk Ω  ")
        QTest.mouseClick(widget.add_button, Qt.MouseButton.LeftButton)
        assert changes.count() == 1
        assert len(widget.names()) == 3
        QTest.mouseClick(widget.up_button, Qt.MouseButton.LeftButton)
        assert widget.names() == ("Earth, Wind & Fire", "  Björk Ω  ", "Heavy; Progressive")
        QTest.mouseClick(widget.down_button, Qt.MouseButton.LeftButton)
        assert widget.names() == ("Earth, Wind & Fire", "Heavy; Progressive", "  Björk Ω  ")
        QTest.mouseClick(widget.remove_button, Qt.MouseButton.LeftButton)
        assert widget.names() == ("Earth, Wind & Fire", "Heavy; Progressive")
        assert changes.count() == 4
        widget.name_edit.setText("  ")
        assert not widget.add_button.isEnabled()
    finally:
        widget.close()
        widget.deleteLater()


def test_artists_and_genres_are_complete_ordered_patch_values(window):
    values = load_detail(window, TrackMetadata(artists=("A, B",), genres=("Rock; Metal",)))
    window.begin_edit(values)
    artists = window.ordered_labels["artists"]
    artists.name_edit.setText("Accept")
    QTest.mouseClick(artists.add_button, Qt.MouseButton.LeftButton)
    QTest.mouseClick(artists.up_button, Qt.MouseButton.LeftButton)
    genres = window.ordered_labels["genres"]
    QTest.mouseClick(genres.remove_button, Qt.MouseButton.LeftButton)
    assert window.edit_patch().as_dict() == {"artists": ("Accept", "A, B"), "genres": ()}
    assert window.save_button.isEnabled()


def test_selection_guard_preserves_draft_before_detail_can_be_cleared(window, qt_app):
    window.begin_edit(load_detail(window))
    replace_text(window.fields["title"], "Unsaved")
    requested = []
    window.selection_guard = lambda file_id: requested.append(file_id) or False
    selected = QSignalSpy(window.track_selected)
    window.table.selectRow(1)
    qt_app.processEvents()
    assert requested == [2]
    assert window.current_file_id() == 1
    assert window.table.currentIndex().row() == 0
    assert window.fields["title"].text() == "Unsaved"
    assert selected.count() == 0
    window.set_edit_state(False)
    window.selection_guard = lambda file_id: True
    window.select_file(2)
    assert window.current_file_id() == 2
    assert selected.at(0) == [2]
    assert window.fields["title"].text() == ""


def test_saving_disables_navigation_and_keeps_draft_on_error(window):
    window.begin_edit(load_detail(window))
    replace_text(window.fields["title"], "Unsaved")
    window.set_edit_state(True, saving=True)
    assert window.edit_status.text() == "Guardando cambios…"
    assert not window.open_button.isEnabled()
    assert not window.import_button.isEnabled()
    assert not window.refresh_button.isEnabled()
    assert not window.table.isEnabled()
    assert not window.fields["title"].isEnabled()
    assert not window.save_button.isEnabled()
    assert not window.cancel_edit_button.isEnabled()
    window.set_detail(
        CatalogEntry(2, 12, Path("unavailable"), "2.flac", TrackMetadata(title="Late"))
    )
    assert window.fields["title"].text() == "Unsaved"
    window.set_edit_state(True)
    window.set_error("El registro ha cambiado. Recarga o revisa el borrador.")
    assert window.fields["title"].text() == "Unsaved"
    assert window.edit_dirty()
    assert window.save_button.isEnabled()
    assert window.cancel_edit_button.isEnabled()


def test_native_edit_save_and_cancel_actions_emit_intentions(window, qt_app):
    values = load_detail(window)
    edited = QSignalSpy(window.edit_requested)
    saved = QSignalSpy(window.save_requested)
    cancelled = QSignalSpy(window.cancel_edit_requested)
    window.activateWindow()
    window.fields["title"].setFocus()
    qt_app.processEvents()
    assert window.edit_action.shortcut() == QKeySequence("Ctrl+E")
    assert window.save_action.shortcut() == QKeySequence(QKeySequence.StandardKey.Save)
    QTest.keyClick(window.fields["title"], Qt.Key.Key_E, Qt.KeyboardModifier.ControlModifier)
    assert edited.count() == 1
    window.begin_edit(values)
    replace_text(window.fields["title"], "Updated")
    QTest.keyClick(window.fields["title"], Qt.Key.Key_S, Qt.KeyboardModifier.ControlModifier)
    assert saved.count() == 1
    QTest.keyClick(window.fields["title"], Qt.Key.Key_Escape)
    assert cancelled.count() == 1


def test_suggestions_request_has_field_and_query(window):
    window.begin_edit(load_detail(window))
    queries = QSignalSpy(window.suggestions_requested)
    artists = window.ordered_labels["artists"]
    replace_text(artists.name_edit, "Acc")
    assert queries.at(queries.count() - 1) == ["artists", "Acc"]
    window.set_suggestions("artists", ("Accept", "Accept", "ACCEPT"))
    assert artists.completer.model().stringList() == ["Accept", "ACCEPT"]


def test_reimport_update_explains_manual_corrections_are_replaced(qt_app, tmp_path):
    dialog = ImportDialog(None, tmp_path / "catalog.tfo", tmp_path)
    try:
        assert "se sustituirán los valores del catálogo" in dialog.update_note.text()
        assert "correcciones manuales" in dialog.update_note.text()
        assert not dialog.update_note.isHidden()
        dialog.create_radio.setChecked(True)
        assert dialog.update_note.isHidden()
    finally:
        dialog.close()
        dialog.deleteLater()
