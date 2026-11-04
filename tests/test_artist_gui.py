"""Artist browsing through the real catalogue worker and existing album navigation."""

import pytest

pytest.importorskip("PySide6")

from test_album_gui import library
from test_catalog_edit import edit
from test_import_gui_integration import wait_until
from test_tag_write import setup_tags as setup_tags
from test_tag_write_gui import open_window, teardown


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
