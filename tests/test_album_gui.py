"""Real album navigation and atomic editing through the Qt workers."""
# ruff: noqa: E402

from dataclasses import replace

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QMessageBox
from test_import_gui_integration import wait_until
from test_tag_write import make_source
from test_tag_write import setup_tags as setup_tags
from test_tag_write_gui import open_window, teardown

from trackfolio.infrastructure.metadata import read_metadata


def library(setup_tags, tmp_path):
    _, repository, _, _, _ = setup_tags
    source = make_source(tmp_path, "flac")
    second = source.with_name("b.flac")
    second.write_bytes(source.read_bytes())
    entries = []
    for number, path in enumerate((source, second), 1):
        metadata = replace(
            read_metadata(path),
            title=f"Track {number}",
            track_number=number,
            album_artists=("Album artist",),
            artists=(f"Singer {number}",),
            genres=("Metal",) if number == 1 else ("Rock",),
        )
        entries.append(repository.save(metadata, source.parent, path.name))
    other = source.parent / "Other"
    other.mkdir()
    repository.save(read_metadata(source), other, "unavailable.flac")
    return source, second, tuple(entries)


def show_albums(app, window, controller):
    window.views.setCurrentWidget(window.album_view)
    wait_until(app, lambda: not controller._jobs and window.album_view.current_album is not None)
    view = window.album_view
    for row in range(view.list.count()):
        view.list.setCurrentRow(row)
        wait_until(app, lambda: not controller._jobs)
        if len(view.current_album.tracks) == 2:
            return view
    raise AssertionError("Album with both tracks missing")


def test_album_view_works_offline_and_opens_an_individual_track(qt_app, setup_tags, tmp_path):
    source, second, entries = library(setup_tags, tmp_path)
    source.unlink()
    second.unlink()
    window, controller = open_window(qt_app, setup_tags, entries[0])
    try:
        view = show_albums(qt_app, window, controller)
        assert view.list.count() == 2
        assert view.title.text() == "Old album"
        assert view.artists.text() == "Album artist"
        assert view.table.rowCount() == 2
        assert view.table.item(0, 2).text() == "Track 1"
        assert view.table.item(1, 3).text() == "Singer 2"
        assert not view.cover.pixmap().isNull()
        view.search.setText("Album artist")
        assert sum(not view.list.item(row).isHidden() for row in range(view.list.count())) == 1
        controller.open_album_track(entries[1].file_id)
        wait_until(qt_app, lambda: not controller._jobs)
        assert window.views.currentWidget() is window.splitter
        assert window.current_file_id() == entries[1].file_id
        assert window.fields["title"].text() == "Track 2"
    finally:
        teardown(window, controller)


def test_album_editor_changes_common_data_without_changing_track_artists(
    qt_app, setup_tags, tmp_path
):
    _, repository, _, _, _ = setup_tags
    source, second, entries = library(setup_tags, tmp_path)
    before = source.read_bytes(), second.read_bytes()
    window, controller = open_window(qt_app, setup_tags, entries[0])
    try:
        view = show_albums(qt_app, window, controller)
        QTest.mouseClick(view.edit_button, Qt.MouseButton.LeftButton)
        wait_until(qt_app, lambda: not controller._jobs and view._editing)
        assert not view.dirty()
        assert view.labels["genres"].name_edit.placeholderText() == "Valores distintos"
        view.apply_fields["album"].setChecked(True)
        view.fields["album"].setText("New album")
        view.apply_fields["album_artists"].setChecked(True)
        view.labels["album_artists"].set_names(("Various Artists",))
        QTest.mouseClick(view.save_button, Qt.MouseButton.LeftButton)
        wait_until(
            qt_app, lambda: not controller._jobs and not controller.saving and not view._editing
        )
        assert view.title.text() == "New album"
        assert view.artists.text() == "Various Artists"
        assert source.read_bytes() == before[0] and second.read_bytes() == before[1]
        for index, entry in enumerate(entries, 1):
            actual = repository.get(entry.file_id).metadata
            assert actual.artists == (f"Singer {index}",)
            assert actual.album_artists == ("Various Artists",)
            assert actual.album == "New album"
    finally:
        teardown(window, controller)


@pytest.mark.parametrize("answer", ["Cancel", "Discard", "Save"])
def test_switching_views_guards_an_unsaved_album(qt_app, setup_tags, tmp_path, monkeypatch, answer):
    _, repository, _, _, _ = setup_tags
    _, _, entries = library(setup_tags, tmp_path)
    window, controller = open_window(qt_app, setup_tags, entries[0])
    try:
        view = show_albums(qt_app, window, controller)
        controller.start_album_edit()
        wait_until(qt_app, lambda: not controller._jobs and view._editing)
        view.apply_fields["album"].setChecked(True)
        view.fields["album"].setText("Edited")
        monkeypatch.setattr(
            controller, "_confirm_unsaved", lambda: getattr(QMessageBox.StandardButton, answer)
        )
        window.views.setCurrentWidget(window.splitter)
        wait_until(qt_app, lambda: not controller._jobs and not controller.saving)
        assert window.views.currentWidget() is (
            window.album_view if answer == "Cancel" else window.splitter
        )
        assert repository.get(entries[0].file_id).metadata.album == (
            "Edited" if answer == "Save" else "Old album"
        )
        assert view.dirty() == (answer == "Cancel")
    finally:
        teardown(window, controller)


def test_album_write_targets_all_its_tracks_and_updates_nfo(qt_app, setup_tags, tmp_path):
    _, _, _, _, files = setup_tags
    source, _, entries = library(setup_tags, tmp_path)
    nfo = source.parent / "album.nfo"
    nfo.write_text("<album><title>Old</title><artist>Outdated</artist></album>", encoding="utf-8")
    window, controller = open_window(qt_app, setup_tags, entries[0])
    try:
        view = show_albums(qt_app, window, controller)
        QTest.mouseClick(view.write_button, Qt.MouseButton.LeftButton)
        dialog = controller._tag_dialog
        assert set(dialog.file_ids) == {entry.file_id for entry in entries}
        assert not files.journal_root.exists()
        QTest.mouseClick(dialog.write_button, Qt.MouseButton.LeftButton)
        wait_until(qt_app, lambda: not controller._tag_running and dialog._report is not None)
        assert all(item.state == "confirmed" for item in dialog._report.results), dialog._report
        assert len(dialog._report.results) == 2
        assert read_metadata(source).album_artists == ("Album artist",)
        assert "Album artist" in nfo.read_text(encoding="utf-8")
        dialog.reject()
        wait_until(qt_app, lambda: not controller._jobs)
        assert window.views.currentWidget() is window.album_view
    finally:
        teardown(window, controller)


def test_album_keyboard_shortcuts_use_the_visible_editor(qt_app, setup_tags, tmp_path):
    _, repository, _, _, _ = setup_tags
    _, _, entries = library(setup_tags, tmp_path)
    window, controller = open_window(qt_app, setup_tags, entries[0])
    try:
        view = show_albums(qt_app, window, controller)
        assert window.edit_action.isEnabled()
        view.search.setFocus()
        QTest.keySequence(view.search, window.edit_action.shortcut())
        wait_until(qt_app, lambda: not controller._jobs and view._editing)
        assert not window.save_action.isEnabled()
        view.apply_fields["album_year"].setChecked(True)
        view.fields["album_year"].setText("1985")
        assert window.save_action.isEnabled()
        QTest.keySequence(view.fields["album_year"], window.save_action.shortcut())
        wait_until(qt_app, lambda: not controller._jobs and not controller.saving)
        assert repository.get(entries[0].file_id).metadata.album_year == 1985
        assert window.views.currentWidget() is window.album_view and not view._editing
    finally:
        teardown(window, controller)


@pytest.mark.parametrize("destination", ["songs", "other_album", "empty_search"])
def test_leaving_while_album_editor_loads_does_not_redirect_later_song_edits(
    qt_app, setup_tags, tmp_path, monkeypatch, destination
):
    from threading import Event

    _, repository, _, _, _ = setup_tags
    _, _, entries = library(setup_tags, tmp_path)
    window, controller = open_window(qt_app, setup_tags, entries[0])
    started, release = Event(), Event()
    original = controller._edit_factory.open_reader

    def delayed(path):
        started.set()
        assert release.wait(5)
        return original(path)

    try:
        show_albums(qt_app, window, controller)
        monkeypatch.setattr(controller._edit_factory, "open_reader", delayed)
        controller.start_album_edit()
        wait_until(qt_app, started.is_set)
        if destination == "songs":
            window.views.setCurrentWidget(window.splitter)
        elif destination == "empty_search":
            window.album_view.search.setText("No matching album")
        else:
            view = window.album_view
            for row in range(view.list.count()):
                if row != view.list.currentRow():
                    view.list.setCurrentRow(row)
                    break
        release.set()
        wait_until(qt_app, lambda: not controller._jobs)
        assert not controller._album_edit and controller._edit_snapshot is None
        window.views.setCurrentWidget(window.splitter)
        wait_until(qt_app, lambda: not controller._jobs)
        monkeypatch.setattr(controller._edit_factory, "open_reader", original)
        controller.start_edit()
        wait_until(qt_app, lambda: not controller._jobs and controller._edit_snapshot is not None)
        assert not controller._album_edit
        window.fields["title"].setText("Song correction")
        controller.save_edit()
        wait_until(qt_app, lambda: not controller._jobs and not controller.saving)
        assert repository.get(entries[0].file_id).metadata.title == "Song correction"
        assert repository.get(entries[1].file_id).metadata.title == "Track 2"
    finally:
        release.set()
        teardown(window, controller)


def test_invalid_album_year_keeps_draft_and_does_not_save_a_partial_album(
    qt_app, setup_tags, tmp_path
):
    _, repository, _, _, _ = setup_tags
    _, _, entries = library(setup_tags, tmp_path)
    window, controller = open_window(qt_app, setup_tags, entries[0])
    try:
        view = show_albums(qt_app, window, controller)
        controller.start_album_edit()
        wait_until(qt_app, lambda: not controller._jobs and view._editing)
        view.apply_fields["album"].setChecked(True)
        view.fields["album"].setText("Must not save")
        view.apply_fields["album_year"].setChecked(True)
        view.fields["album_year"].setText("0")
        controller.save_edit()
        assert view._editing and view.dirty() and view.error.text()
        assert all(repository.get(entry.file_id).metadata.album == "Old album" for entry in entries)
        assert not controller.saving
    finally:
        teardown(window, controller)
