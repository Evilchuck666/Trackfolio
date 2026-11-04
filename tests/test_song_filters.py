"""Song filters use lightweight metadata and protect real editing/navigation."""
# ruff: noqa: E402

from dataclasses import replace
from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QMessageBox
from test_edit_gui_integration import (
    begin_edit,
    open_ready,
    read_entry,
    replace_text,
    teardown,
)
from test_edit_gui_integration import (
    edit_catalog as edit_catalog,
)
from test_gui_widgets import window as window
from test_import_gui_integration import wait_until

from trackfolio.domain.catalog import CatalogSummary
from trackfolio.infrastructure.preferences import CatalogPreferences
from trackfolio.startup import create_window


def rows():
    return (
        CatalogSummary(1, 11, "First song", ("Björk",), "Debut", 1993, "a.flac", ("Pop", "Jazz")),
        CatalogSummary(2, 12, "Second song", ("Accept",), "Breaker", 1981, "b.flac", ("Metal",)),
        CatalogSummary(3, 13, None, (), None, None, "c.mp3"),
    )


def visible(window):
    return tuple(
        row.file_id
        for i, row in enumerate(window.model.summaries())
        if not window.table.isRowHidden(i)
    )


def choose(combo, value):
    index = combo.findData(value)
    assert index >= 0
    combo.setCurrentIndex(index)


def test_combined_search_genre_year_and_clear_preserve_selection(window):
    window.set_catalog(Path("catalog.tfo"), rows())
    window.select_files((1, 2))
    window.song_search.setText("BJÖRK debut")
    choose(window.song_genre, "Jazz")
    choose(window.song_year, 1993)
    assert visible(window) == (1,)
    assert window.selected_file_ids() == (1,)
    assert window.count_label.text() == "1 / 3"
    choose(window.song_year, 1981)
    assert visible(window) == ()
    assert window.selected_file_ids() == ()
    assert window.current_file_id() is None
    assert window.empty_label.text() == "No songs match your filters."
    window.clear_song_filters.click()
    assert visible(window) == (1, 2, 3)
    assert window.selected_file_ids() == (1,)
    assert window.count_label.text() == "3"


def test_missing_metadata_and_hidden_rows_cannot_be_selected(window):
    window.set_catalog(Path("catalog.tfo"), rows())
    choose(window.song_genre, "")
    choose(window.song_year, 0)
    assert visible(window) == (3,)
    window.select_files((1, 3))
    assert window.selected_file_ids() == (3,)
    assert not window.write_tags_action.isEnabled()


def test_refresh_retains_filters_and_switching_catalog_resets_them(window):
    path = Path("catalog.tfo")
    window.set_catalog(path, rows())
    choose(window.song_genre, "Metal")
    window.set_catalog(path, rows())
    assert visible(window) == (2,)
    assert window.selected_file_ids() == (2,)
    window.model.update_summary(replace(rows()[1], genres=("Rock",)))
    window.refresh_song_filters()
    assert visible(window) == ()
    assert window.count_label.text() == "0 / 3"
    window.set_catalog(Path("other.tfo"), rows())
    assert visible(window) == (1, 2, 3)
    assert window.song_genre.currentData() is None


def test_whole_catalog_action_remains_available_without_matches(window):
    window.set_tag_write_enabled(True)
    window.set_catalog(Path("catalog.tfo"), rows())
    window.song_search.setText("No match")
    assert not window.write_tags_action.isEnabled()
    assert window.write_all_tags_action.isEnabled()
    assert window.model.summaries() == rows()


@pytest.mark.parametrize("answer", ["Cancel", "Discard", "Save"])
def test_filter_navigation_protects_drafts(qt_app, edit_catalog, tmp_path, monkeypatch, answer):
    database, first, second = edit_catalog
    window, controller = create_window(CatalogPreferences(tmp_path / "settings.json"))
    window.views.setCurrentWidget(window.splitter)
    monkeypatch.setattr(
        controller, "_confirm_unsaved", lambda: getattr(QMessageBox.StandardButton, answer)
    )
    try:
        open_ready(qt_app, window, controller, database)
        begin_edit(qt_app, window, controller)
        replace_text(window.fields["title"], "Edited title")
        window.song_search.setText("Sibling")
        if answer == "Cancel":
            assert window.song_search.text() == ""
            assert window.current_file_id() == first.file_id
            assert window.fields["title"].text() == "Edited title"
            assert window.edit_dirty()
        else:
            wait_until(
                qt_app,
                lambda: (
                    window.song_search.text() == "Sibling"
                    and window.fields["title"].text() == "Sibling"
                    and not controller._jobs
                ),
            )
            assert window.selected_file_ids() == (second.file_id,)
            assert visible(window) == (second.file_id,)
        assert read_entry(database, first.file_id).metadata.title == (
            "Edited title" if answer == "Save" else "Original"
        )
    finally:
        teardown(window, controller)


def test_save_reapplies_active_search(qt_app, edit_catalog, tmp_path):
    database, first, second = edit_catalog
    window, controller = create_window(CatalogPreferences(tmp_path / "settings.json"))
    window.views.setCurrentWidget(window.splitter)
    try:
        open_ready(qt_app, window, controller, database)
        window.song_search.setText("Original")
        begin_edit(qt_app, window, controller)
        replace_text(window.fields["title"], "Renamed")
        window.save_button.click()
        wait_until(qt_app, lambda: not controller._jobs and not controller.saving)
        assert visible(window) == ()
        assert window.current_file_id() is None
        assert window.fields["title"].text() == ""
        assert read_entry(database, first.file_id).metadata.title == "Renamed"
    finally:
        teardown(window, controller)


def test_failed_save_keeps_filter_and_draft(qt_app, edit_catalog, tmp_path, monkeypatch):
    database, first, _ = edit_catalog
    window, controller = create_window(CatalogPreferences(tmp_path / "settings.json"))
    window.views.setCurrentWidget(window.splitter)
    monkeypatch.setattr(controller, "_confirm_unsaved", lambda: QMessageBox.StandardButton.Save)
    try:
        open_ready(qt_app, window, controller, database)
        begin_edit(qt_app, window, controller)
        replace_text(window.fields["title"], "Unsaved title")
        # The track number cannot exceed the existing total of two.
        replace_text(window.fields["track_number"], "99")
        window.song_search.setText("Sibling")
        wait_until(qt_app, lambda: not controller._jobs and not controller.saving)
        assert window.song_search.text() == ""
        assert window.current_file_id() == first.file_id
        assert window.fields["title"].text() == "Unsaved title"
        assert window.edit_dirty()
        assert read_entry(database, first.file_id).metadata.title == "Original"
    finally:
        teardown(window, controller)
