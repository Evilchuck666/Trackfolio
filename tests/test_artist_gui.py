"""Artist browsing through the real catalogue worker and existing album navigation."""

import pytest

pytest.importorskip("PySide6")

from PySide6.QtGui import QImage
from test_album_gui import library
from test_catalog_edit import edit
from test_import_gui_integration import wait_until
from test_tag_write import setup_tags as setup_tags
from test_tag_write_gui import open_window, teardown

from trackfolio.startup import create_window


def test_artist_search_and_album_navigation_work_offline(qt_app, setup_tags, tmp_path):
    source, second, entries = library(setup_tags, tmp_path)
    source.unlink()
    second.unlink()
    window, controller = open_window(qt_app, setup_tags, entries[0])
    try:
        window.views.setCurrentWidget(window.artist_view)
        wait_until(qt_app, lambda: not controller._jobs)
        view = window.artist_view
        view.search.setText("album artist")
        assert view.title.text() == "Album artist"
        assert view.albums.count() == 1
        assert not window.edit_action.isEnabled()
        assert not window.write_tags_action.isEnabled()
        view.search.setText("no matches")
        assert view.albums.count() == 0 and not view.open_button.isEnabled()
        view.search.clear()
        view.search.setText("album artist")
        view.open_button.click()
        wait_until(qt_app, lambda: not controller._jobs)
        assert window.views.currentWidget() is window.album_view
        assert set(window.album_view.current_album.file_ids) == {entry.file_id for entry in entries}
        window.views.setCurrentWidget(view)
        wait_until(qt_app, lambda: not controller._jobs)
        assert view.search.text() == "album artist"
        assert view.title.text() == "Album artist"
        database = setup_tags[0]
        for entry in entries:
            edit(database, entry.file_id, album_artists=("Renamed",))
        controller.refresh()
        wait_until(qt_app, lambda: not controller._jobs)
        assert view.albums.count() == 0
        view.search.setText("renamed")
        assert view.title.text() == "Renamed" and view.albums.count() == 1
    finally:
        teardown(window, controller)


def test_artist_portrait_loads_and_clears_when_unavailable(qt_app, setup_tags, tmp_path):
    source, _, _ = library(setup_tags, tmp_path)
    portrait = source.parent.parent / "artist.JPG"
    image = QImage(80, 40, QImage.Format.Format_RGB32)
    image.fill(0xFF008800)
    assert image.save(str(portrait), "JPEG")
    window, controller = create_window(tag_journal_root=tmp_path / "journal")
    try:
        controller.open_database(setup_tags[0])
        wait_until(qt_app, lambda: not controller._jobs)
        view = window.artist_view
        view.search.setText("album artist")
        wait_until(qt_app, lambda: not controller._jobs)
        assert not view.cover.pixmap().isNull()
        assert view.cover.pixmap().width() > view.cover.pixmap().height()
        view.search.setText("no matches")
        assert view.cover.pixmap().isNull()
        portrait.unlink()
        view.search.setText("album artist")
        wait_until(qt_app, lambda: not controller._jobs)
        assert view.cover.pixmap().isNull()
    finally:
        teardown(window, controller)
