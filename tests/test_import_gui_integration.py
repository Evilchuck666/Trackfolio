"""Import real temporary audio through the GUI and exercise worker ownership."""
# ruff: noqa: E402

from __future__ import annotations

import os
import subprocess
import sys
import textwrap
import threading
import time

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QTimer
from PySide6.QtTest import QSignalSpy, QTest
from test_gui_integration import ControlledSession
from test_metadata import png, write_flac, write_mp3

from trackfolio.application.import_catalog import ImportCatalog, ImportRequest
from trackfolio.infrastructure.audio_scan import FileSystemAudioScanner
from trackfolio.infrastructure.import_target import SqliteImportTargetFactory
from trackfolio.infrastructure.metadata import read_metadata
from trackfolio.infrastructure.preferences import CatalogPreferences
from trackfolio.infrastructure.session import open_catalog
from trackfolio.interfaces.gui.controller import CatalogController
from trackfolio.interfaces.gui.lifecycle import dispose_window
from trackfolio.interfaces.gui.window import MainWindow
from trackfolio.startup import create_window


def wait_until(app, predicate, timeout=5):
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        app.processEvents()
        QTest.qWait(5)
    assert predicate(), "Timed out waiting for an import result"


def test_import_and_reimport_real_audio_then_read_without_music(qt_app, tmp_path):
    music = tmp_path / "Música con espacios"
    music.mkdir()
    source = write_flac(
        music / "a.FLAC",
        [("TITLE", "Canción"), ("ARTIST", "Artista"), ("LYRICS", "Texto\nOtra línea")],
        [(3, png())],
    )
    untagged = write_mp3(music / "b.mp3")
    (music / "c.flac").write_bytes(b"invalid audio")
    database = tmp_path / "catalogo.tfo"
    preferences = CatalogPreferences(tmp_path / "settings.json")
    window, controller = create_window(preferences)
    reports = []
    controller.import_finished.connect(reports.append)
    window.show()
    try:
        controller.start_import(ImportRequest(music, database, "create"))
        wait_until(qt_app, lambda: len(reports) == 1 and window.fields["title"].text() == "Canción")
        assert (reports[0].created, reports[0].updated, reports[0].failed) == (2, 0, 1)
        assert window.model.rowCount() == 2
        assert preferences.last_catalog() == database
        assert window.lyrics.toPlainText() == "Texto\nOtra línea"
        assert not window.cover.pixmap().isNull()
        window.table.selectRow(1)
        wait_until(qt_app, lambda: window.fields["title"].text() == "")
        selected = window.current_file_id()
        write_flac(source, [])
        controller.start_import(ImportRequest(music, database, "update"))
        wait_until(qt_app, lambda: len(reports) == 2 and not controller._jobs)
        assert (reports[1].created, reports[1].updated, reports[1].failed) == (0, 2, 1)
        assert window.current_file_id() == selected
        assert window.model.rowCount() == 2
        source.unlink()
        untagged.unlink()
        controller.refresh()
        wait_until(qt_app, lambda: not controller._jobs)
        assert window.model.rowCount() == 2
        assert all(field.text() == "" for field in window.fields.values())
    finally:
        controller.shutdown()
        dispose_window(window)


class GateReader:
    def __init__(self):
        self.started = threading.Event()
        self.release = threading.Event()

    def __call__(self, path):
        if path.name == "b.flac":
            self.started.set()
            assert self.release.wait(5), "The test must release the reader"
        return read_metadata(path)


@pytest.mark.parametrize("closing", [False, True])
def test_cancel_or_close_remains_responsive_and_keeps_committed_files(qt_app, tmp_path, closing):
    music = tmp_path / "music"
    music.mkdir()
    write_flac(music / "a.flac", [("TITLE", "Guardada")])
    write_flac(music / "b.flac", [("TITLE", "Pendiente")])
    database = tmp_path / "partial.tfo"
    gate = GateReader()
    importer = ImportCatalog(FileSystemAudioScanner(), gate, SqliteImportTargetFactory())
    window = MainWindow()
    controller = CatalogController(window, open_catalog, importer=importer)
    reports = []
    controller.import_finished.connect(reports.append)
    closed = QSignalSpy(window.closing)
    window.show()
    try:
        controller.start_import(ImportRequest(music, database, "create"))
        wait_until(qt_app, gate.started.is_set)
        assert not window.import_button.isEnabled()
        assert not window.open_button.isEnabled()
        assert not window.table.isEnabled()
        # A second request cannot start another writer while this one is active.
        controller.start_import(ImportRequest(music, tmp_path / "other.tfo", "create"))
        assert not (tmp_path / "other.tfo").exists()
        if closing:
            assert not window.close()
            assert window.isVisible() and closed.count() == 0
        else:
            controller.cancel_import()
        timer_ran = []
        QTimer.singleShot(0, lambda: timer_ran.append(True))
        wait_until(qt_app, lambda: bool(timer_ran))
        assert not gate.release.is_set()
        gate.release.set()
        wait_until(qt_app, lambda: bool(reports))
        assert reports[0].state == "cancelled"
        assert (reports[0].created, reports[0].failed, reports[0].pending) == (1, 0, 1)
        if closing:
            wait_until(qt_app, lambda: closed.count() == 1)
            assert not window.isVisible()
            assert controller._closed and not controller._pool.activeThreadCount()
        else:
            wait_until(qt_app, lambda: window.model.rowCount() == 1 and not controller._jobs)
            assert window.fields["title"].text() == "Guardada"
            assert window.import_button.isEnabled()
        session = open_catalog(database)
        try:
            assert len(session.list_summaries()) == 1
        finally:
            session.close()
    finally:
        gate.release.set()
        controller.shutdown()
        dispose_window(window)


def test_empty_import_restores_previous_catalog_and_selection(qt_app, tmp_path):
    music = tmp_path / "music"
    music.mkdir()
    write_flac(music / "a.flac", [("TITLE", "Anterior")])
    database = tmp_path / "previous.tfo"
    window, controller = create_window(CatalogPreferences(tmp_path / "settings.json"))
    reports = []
    controller.import_finished.connect(reports.append)
    try:
        controller.start_import(ImportRequest(music, database, "create"))
        wait_until(qt_app, lambda: window.fields["title"].text() == "Anterior")
        selected = window.current_file_id()
        empty = tmp_path / "empty"
        empty.mkdir()
        destination = tmp_path / "unused.tfo"
        controller.start_import(ImportRequest(empty, destination, "create"))
        wait_until(qt_app, lambda: len(reports) == 2 and not controller._jobs)
        assert reports[-1].total == 0
        assert not destination.exists()
        assert window.current_file_id() == selected
        assert window.fields["title"].text() == "Anterior"
    finally:
        controller.shutdown()
        dispose_window(window)


def test_dispose_window_defers_deletion_until_import_worker_finishes(qt_app, tmp_path):
    music = tmp_path / "music"
    music.mkdir()
    write_flac(music / "b.flac")
    gate = GateReader()
    window = MainWindow()
    controller = CatalogController(
        window,
        open_catalog,
        importer=ImportCatalog(FileSystemAudioScanner(), gate, SqliteImportTargetFactory()),
    )
    destroyed = QSignalSpy(window.destroyed)
    controller.start_import(ImportRequest(music, tmp_path / "cancelled.tfo", "create"))
    wait_until(qt_app, gate.started.is_set)
    dispose_window(window)
    qt_app.processEvents()
    assert destroyed.count() == 0
    gate.release.set()
    wait_until(qt_app, lambda: destroyed.count() == 1)
    assert not (tmp_path / "cancelled.tfo").exists()


def test_import_waits_for_previous_detail_and_closes_reader(qt_app, tmp_path):
    music = tmp_path / "music"
    music.mkdir()
    write_flac(music / "new.flac", [("TITLE", "Importada")])
    previous = ControlledSession(tmp_path / "old.tfo", delay_first=True)
    scanned = threading.Event()

    class CheckedScanner(FileSystemAudioScanner):
        def scan(self, *args):
            assert previous.closed, "The old reader must close before a writer starts"
            scanned.set()
            return super().scan(*args)

    def opener(path):
        return previous if path == previous.database_path else open_catalog(path)

    window = MainWindow()
    controller = CatalogController(
        window,
        opener,
        importer=ImportCatalog(CheckedScanner(), read_metadata, SqliteImportTargetFactory()),
    )
    try:
        controller.open_database(previous.database_path)
        wait_until(qt_app, previous.started.is_set)
        controller.start_import(ImportRequest(music, tmp_path / "new.tfo", "create"))
        qt_app.processEvents()
        assert not scanned.is_set()
        previous.release.set()
        wait_until(qt_app, lambda: window.fields["title"].text() == "Importada")
        assert scanned.is_set() and previous.closed
    finally:
        previous.release.set()
        controller.shutdown()
        dispose_window(window)


def test_application_quit_defers_until_a_timer_can_release_the_import_worker(tmp_path):
    script = textwrap.dedent("""
        import sys
        import threading
        from pathlib import Path
        from PySide6.QtCore import QTimer
        from trackfolio.application.import_catalog import ImportCatalog, ImportRequest
        from trackfolio.domain.metadata import TrackMetadata
        from trackfolio.infrastructure.audio_scan import FileSystemAudioScanner
        from trackfolio.infrastructure.import_target import SqliteImportTargetFactory
        from trackfolio.infrastructure.session import open_catalog
        from trackfolio.interfaces.gui.app import CatalogApplication
        from trackfolio.interfaces.gui.controller import CatalogController
        from trackfolio.interfaces.gui.lifecycle import dispose_window
        from trackfolio.interfaces.gui.theme import apply_theme
        from trackfolio.interfaces.gui.window import MainWindow

        root = Path(sys.argv[1])
        music = root / 'music'
        music.mkdir()
        (music / 'a.flac').write_bytes(b'controlled fixture')
        (music / 'b.flac').write_bytes(b'controlled fixture')
        started = threading.Event()
        release = threading.Event()

        def reader(path):
            if path.name == 'b.flac':
                started.set()
                assert release.wait(4), 'Quit blocked the event loop'
            return TrackMetadata(title=path.name, audio_format='flac')

        app = CatalogApplication([])
        apply_theme(app)
        window = MainWindow()
        controller = CatalogController(window, open_catalog, importer=ImportCatalog(
            FileSystemAudioScanner(), reader, SqliteImportTargetFactory()))
        app.close_guard = controller.request_close
        app.aboutToQuit.connect(controller.shutdown)
        reports = []
        controller.import_finished.connect(reports.append)
        window.show()
        pulse = QTimer()

        def try_quit():
            if started.is_set():
                pulse.stop()
                app.quit()
                # This callback must still run after the quit request.
                QTimer.singleShot(20, release.set)

        pulse.timeout.connect(try_quit)
        pulse.start(5)
        QTimer.singleShot(0, lambda: controller.start_import(
            ImportRequest(music, root / 'partial.tfo', 'create')))

        def watchdog():
            release.set()
            app.exit(7)

        QTimer.singleShot(5000, watchdog)
        exit_code = app.exec()
        assert exit_code == 0 and release.is_set()
        assert reports and reports[0].state == 'cancelled' and reports[0].saved == 1
        assert controller._closed and not controller._pool.activeThreadCount()
        controller.shutdown()
        app.close_guard = None
        dispose_window(window)
        print('Quit deferred; worker released before Qt disposal')
    """)
    result = subprocess.run(
        [sys.executable, "-c", script, str(tmp_path)],
        env={**os.environ, "QT_QPA_PLATFORM": "offscreen"},
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Quit deferred" in result.stdout


def test_import_finished_observer_can_start_another_import(qt_app, tmp_path):
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    write_flac(first / "a.flac", [("TITLE", "Primera")])
    write_flac(second / "b.flac", [("TITLE", "Segunda")])
    window, controller = create_window(CatalogPreferences(tmp_path / "settings.json"))
    reports = []

    def finished(report):
        reports.append(report)
        if len(reports) == 1:
            controller.start_import(ImportRequest(second, tmp_path / "second.tfo", "create"))

    controller.import_finished.connect(finished)
    try:
        controller.start_import(ImportRequest(first, tmp_path / "first.tfo", "create"))
        wait_until(qt_app, lambda: len(reports) == 2 and window.fields["title"].text() == "Segunda")
        assert not controller.importing
        assert reports[0].saved == reports[1].saved == 1
        assert window.model.rowCount() == 1
    finally:
        controller.shutdown()
        dispose_window(window)
