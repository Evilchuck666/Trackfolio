"""Exercise the asynchronous viewer against SQLite and controlled delayed adapters."""
# ruff: noqa: E402

from __future__ import annotations

import threading
import time
from dataclasses import replace
from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from PySide6.QtTest import QTest

from trackfolio.domain.catalog import CatalogEntry, CatalogSummary
from trackfolio.domain.metadata import Artwork, TrackMetadata
from trackfolio.infrastructure.catalog import SqliteCatalogRepository
from trackfolio.infrastructure.database import create_engine, migrate_database
from trackfolio.infrastructure.session import open_catalog
from trackfolio.interfaces.gui.controller import CatalogController
from trackfolio.interfaces.gui.probe import _image
from trackfolio.interfaces.gui.window import MainWindow


def wait_until(app, predicate, timeout=4):
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        app.processEvents()
        QTest.qWait(5)
    assert predicate(), "Timed out waiting for a GUI result"


@pytest.fixture
def catalog(tmp_path):
    database = tmp_path / "DB con espacios % #.sqlite3"
    migrate_database(database)
    engine = create_engine(database)
    try:
        repository = SqliteCatalogRepository(engine)
        full = repository.save(
            TrackMetadata(
                title="Canción",
                artists=("Artista B", "Artista A"),
                album="Álbum",
                album_year=1981,
                track_number=3,
                track_total=10,
                disc_number=1,
                disc_total=2,
                genres=("Rock", "Jazz"),
                lyrics="<b>Texto literal</b>\nOtra línea",
                artwork=Artwork(_image(), "image/bmp", 1, 1),
                audio_format="flac",
            ),
            tmp_path / "music-not-present",
            "missing.flac",
        )
        empty = repository.save(
            TrackMetadata(audio_format="mp3"), tmp_path / "music-not-present", "untagged.mp3"
        )
    finally:
        engine.dispose()
    return database, full, empty


def test_gui_reads_sqlite_with_no_music_then_clears_every_missing_field(qt_app, catalog):
    database, full, empty = catalog
    window = MainWindow()
    controller = CatalogController(window, open_catalog)
    completed = []
    controller.detail_loaded.connect(completed.append)
    window.show()
    try:
        controller.open_database(database)
        wait_until(qt_app, lambda: completed == [full.file_id])
        assert window.model.rowCount() == 2
        assert window.fields["title"].text() == "Canción"
        assert window.fields["artists"].text() == "Artista B; Artista A"
        assert window.fields["album"].text() == "Álbum"
        assert window.fields["album_year"].text() == "1981"
        assert window.fields["track_number"].text() == "3"
        assert window.fields["track_total"].text() == "10"
        assert window.fields["disc_number"].text() == "1"
        assert window.fields["disc_total"].text() == "2"
        assert window.fields["genres"].text() == "Rock; Jazz"
        assert window.lyrics.toPlainText() == "<b>Texto literal</b>\nOtra línea"
        assert not window.cover.pixmap().isNull()
        window.table.selectRow(1)
        wait_until(qt_app, lambda: completed == [full.file_id, empty.file_id])
        assert all(field.text() == "" for field in window.fields.values())
        assert window.lyrics.toPlainText() == ""
        assert window.cover.pixmap().isNull()
    finally:
        window.close()


def test_refresh_preserves_selection_and_reloads_changed_values(qt_app, catalog):
    database, _, empty = catalog
    window = MainWindow()
    controller = CatalogController(window, open_catalog)
    completed = []
    controller.detail_loaded.connect(completed.append)
    try:
        controller.open_database(database)
        wait_until(qt_app, lambda: len(completed) == 1)
        window.table.selectRow(1)
        wait_until(qt_app, lambda: completed[-1] == empty.file_id)
        writer = create_engine(database)
        try:
            SqliteCatalogRepository(writer).save(
                replace(empty.metadata, title="Updated externally"),
                empty.library_root,
                empty.relative_path,
            )
        finally:
            writer.dispose()
        completed.clear()
        controller.refresh()
        wait_until(qt_app, lambda: completed == [empty.file_id])
        assert window.current_file_id() == empty.file_id
        assert window.fields["title"].text() == "Updated externally"
    finally:
        window.close()


@pytest.mark.parametrize("kind", ["missing", "foreign", "empty"])
def test_bad_catalog_is_recoverable_then_a_valid_one_opens(qt_app, catalog, tmp_path, kind):
    database, full, _ = catalog
    invalid = tmp_path / f"{kind}.sqlite3"
    if kind == "foreign":
        import sqlite3

        with sqlite3.connect(invalid) as connection:
            connection.execute("CREATE TABLE foreign_data (id INTEGER)")
    elif kind == "empty":
        invalid.touch()
    before = invalid.read_bytes() if invalid.exists() else None
    window = MainWindow()
    controller = CatalogController(window, open_catalog)
    completed = []
    controller.detail_loaded.connect(completed.append)
    try:
        controller.open_database(invalid)
        wait_until(qt_app, lambda: bool(window.error_label.text()))
        assert window.model.rowCount() == 0
        assert all(field.text() == "" for field in window.fields.values())
        assert invalid.exists() == (before is not None)
        if before is not None:
            assert invalid.read_bytes() == before
        controller.open_database(database)
        wait_until(qt_app, lambda: completed == [full.file_id])
        assert window.error_label.text() == ""
        assert window.fields["title"].text() == "Canción"
    finally:
        window.close()


class ControlledSession:
    def __init__(self, path, delay_first=False):
        self.database_path = path
        self.closed = False
        self.started = threading.Event()
        self.release = threading.Event()
        self.returned = threading.Event()
        self.delay_first = delay_first
        self.entries = {
            identifier: CatalogEntry(
                identifier,
                identifier,
                Path("missing"),
                f"{identifier}.flac",
                TrackMetadata(title=title, audio_format="flac"),
            )
            for identifier, title in ((1, "Older"), (2, "Newest"))
        }

    def list_summaries(self):
        return tuple(
            CatalogSummary(
                entry.file_id,
                entry.track_id,
                entry.metadata.title,
                (),
                None,
                None,
                entry.relative_path,
            )
            for entry in self.entries.values()
        )

    def get(self, file_id):
        if file_id == 1 and self.delay_first:
            self.started.set()
            assert self.release.wait(timeout=3)
            self.returned.set()
        return self.entries.get(file_id)

    def close(self):
        self.closed = True


def test_out_of_order_detail_does_not_replace_new_selection(qt_app, tmp_path):
    session = ControlledSession(tmp_path / "fake.db", delay_first=True)
    window = MainWindow()
    controller = CatalogController(window, lambda _: session)
    completed = []
    controller.detail_loaded.connect(completed.append)
    try:
        controller.open_database(session.database_path)
        wait_until(qt_app, session.started.is_set)
        window.table.selectRow(1)
        wait_until(qt_app, lambda: completed == [2])
        assert window.fields["title"].text() == "Newest"
        session.release.set()
        wait_until(qt_app, session.returned.is_set)
        QTest.qWait(50)
        assert window.fields["title"].text() == "Newest"
        assert completed == [2]
    finally:
        session.release.set()
        window.close()
    assert session.closed


def test_out_of_order_catalog_is_discarded_and_sessions_close(qt_app, tmp_path):
    older = ControlledSession(tmp_path / "older.db")
    newer = ControlledSession(tmp_path / "newer.db")
    started = threading.Event()
    release = threading.Event()

    def opener(path):
        if path == older.database_path:
            started.set()
            assert release.wait(timeout=3)
            return older
        return newer

    window = MainWindow()
    controller = CatalogController(window, opener)
    loaded = []
    controller.detail_loaded.connect(loaded.append)
    try:
        controller.open_database(older.database_path)
        wait_until(qt_app, started.is_set)
        controller.open_database(newer.database_path)
        wait_until(qt_app, lambda: loaded == [1])
        release.set()
        wait_until(qt_app, lambda: older.closed)
        assert not newer.closed
        assert window.fields["title"].text() == "Older"
        # Both catalogs use file_id 1; the selected catalog must remain the new one.
        assert window.model.rowCount() == 2
    finally:
        release.set()
        window.close()
    assert older.closed and newer.closed


def test_refresh_to_empty_discards_in_flight_detail(qt_app, tmp_path):
    class SnapshotSession(ControlledSession):
        def get(self, file_id):
            snapshot = self.entries.get(file_id)
            self.started.set()
            assert self.release.wait(timeout=3)
            self.returned.set()
            return snapshot

    session = SnapshotSession(tmp_path / "fake.db")
    window = MainWindow()
    controller = CatalogController(window, lambda _: session)
    completed = []
    controller.detail_loaded.connect(completed.append)
    try:
        controller.open_database(session.database_path)
        wait_until(qt_app, session.started.is_set)
        session.entries.clear()
        controller.refresh()
        wait_until(qt_app, lambda: window.model.rowCount() == 0)
        session.release.set()
        wait_until(qt_app, session.returned.is_set)
        QTest.qWait(50)
        assert window.current_file_id() is None
        assert all(field.text() == "" for field in window.fields.values())
        assert completed == []
    finally:
        session.release.set()
        window.close()


def test_refresh_retains_a_selection_changed_while_query_was_pending(qt_app, tmp_path):
    class SlowListing(ControlledSession):
        calls = 0

        def list_summaries(self):
            self.calls += 1
            rows = super().list_summaries()
            if self.calls == 2:
                self.started.set()
                assert self.release.wait(timeout=3)
            return rows

    session = SlowListing(tmp_path / "fake.db")
    window = MainWindow()
    controller = CatalogController(window, lambda _: session)
    completed = []
    controller.detail_loaded.connect(completed.append)
    try:
        controller.open_database(session.database_path)
        wait_until(qt_app, lambda: completed == [1])
        controller.refresh()
        wait_until(qt_app, session.started.is_set)
        window.table.selectRow(1)
        wait_until(qt_app, lambda: completed == [1, 2])
        session.release.set()
        wait_until(qt_app, lambda: completed == [1, 2, 2])
        assert window.current_file_id() == 2
        assert window.fields["title"].text() == "Newest"
    finally:
        session.release.set()
        window.close()


def test_empty_catalog_is_valid(qt_app, tmp_path):
    session = ControlledSession(tmp_path / "fake.db")
    session.entries.clear()
    window = MainWindow()
    controller = CatalogController(window, lambda _: session)
    loaded = []
    controller.catalog_loaded.connect(lambda: loaded.append(True))
    try:
        controller.open_database(session.database_path)
        wait_until(qt_app, lambda: loaded)
        assert window.model.rowCount() == 0
        assert window.error_label.text() == ""
        assert all(field.text() == "" for field in window.fields.values())
    finally:
        window.close()


def test_detail_query_failure_is_recoverable_on_refresh(qt_app, tmp_path):
    class UnavailableSession(ControlledSession):
        failing = True

        def get(self, file_id):
            if self.failing:
                raise RuntimeError("El catálogo está bloqueado temporalmente.")
            return super().get(file_id)

    session = UnavailableSession(tmp_path / "fake.db")
    window = MainWindow()
    controller = CatalogController(window, lambda _: session)
    loaded = []
    controller.detail_loaded.connect(loaded.append)
    try:
        controller.open_database(session.database_path)
        wait_until(qt_app, lambda: bool(window.error_label.text()))
        assert all(field.text() == "" for field in window.fields.values())
        session.failing = False
        controller.refresh()
        wait_until(qt_app, lambda: loaded == [1])
        assert window.fields["title"].text() == "Older"
        assert window.error_label.text() == ""
    finally:
        window.close()


def test_close_waits_for_worker_and_closes_unaccepted_session(qt_app, tmp_path):
    session = ControlledSession(tmp_path / "fake.db")
    started = threading.Event()

    def opener(_):
        started.set()
        time.sleep(0.03)
        return session

    window = MainWindow()
    controller = CatalogController(window, opener)
    controller.open_database(session.database_path)
    wait_until(qt_app, started.is_set)
    window.close()
    assert session.closed
