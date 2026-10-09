"""Exercise editing through real Qt widgets, workers and temporary SQLite files."""
# ruff: noqa: E402

from __future__ import annotations

import sqlite3
import threading
from contextlib import closing
from dataclasses import replace

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import Qt, QTimer
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QMessageBox
from test_catalog_edit import legacy_catalog
from test_import_gui_integration import wait_until

from trackfolio.application.edit_catalog import CatalogEditError
from trackfolio.application.import_catalog import ImportRequest
from trackfolio.domain.metadata import RawTagValue, TrackMetadata
from trackfolio.infrastructure.catalog import SqliteCatalogRepository
from trackfolio.infrastructure.catalog_edit import SqliteCatalogEditSessionFactory
from trackfolio.infrastructure.database import create_engine, migrate_database
from trackfolio.infrastructure.preferences import CatalogPreferences
from trackfolio.infrastructure.session import open_catalog
from trackfolio.interfaces.gui.controller import CatalogController
from trackfolio.interfaces.gui.lifecycle import dispose_window
from trackfolio.interfaces.gui.window import MainWindow
from trackfolio.startup import create_window


@pytest.fixture
def edit_catalog(tmp_path):
    database = tmp_path / "Editable catálogo % #.tfo"
    migrate_database(database)
    engine = create_engine(database)
    try:
        repository = SqliteCatalogRepository(engine)
        metadata = TrackMetadata(
            title="Original",
            artists=("Abbath",),
            album="Shared album",
            album_year=2020,
            album_date="2020-05-03",
            album_artists=("Abbath",),
            track_number=1,
            track_total=2,
            genres=("Metal",),
            lyrics="Original lyrics\nSecond line",
            raw_tags=(RawTagValue("ARTIST", "Abbath", 0),),
            audio_format="flac",
        )
        first = repository.save(metadata, tmp_path / "missing music", "album/01.flac")
        second = repository.save(
            replace(metadata, title="Sibling", artists=("Accept",), track_number=2),
            first.library_root,
            "album/02.flac",
        )
    finally:
        engine.dispose()
    return database, first, second


def read_entry(database, file_id):
    session = open_catalog(database)
    try:
        return session.get(file_id)
    finally:
        session.close()


def replace_text(field, text):
    field.setFocus()
    field.selectAll()
    if text:
        QTest.keyClicks(field, text)
    else:
        QTest.keyClick(field, Qt.Key.Key_Backspace)


def open_ready(app, window, controller, database, expected="Original"):
    window.show()
    controller.open_database(database)
    wait_until(app, lambda: window.fields["title"].text() == expected and not controller._jobs)


def begin_edit(app, window, controller):
    started = QSignalSpy(controller.edit_started)
    QTest.mouseClick(window.edit_button, Qt.MouseButton.LeftButton)
    wait_until(app, lambda: started.count() == 1 and not controller._jobs)
    assert not window.fields["title"].isReadOnly()
    assert not window.save_button.isEnabled()


def teardown(window, controller):
    controller.shutdown()
    dispose_window(window)


def test_save_reopens_and_updates_summary_detail_and_unique_artist(qt_app, edit_catalog, tmp_path):
    database, first, second = edit_catalog
    preferences = CatalogPreferences(tmp_path / "settings.json")
    window, controller = create_window(preferences)
    finished = []
    controller.edit_finished.connect(finished.append)
    try:
        open_ready(qt_app, window, controller, database)
        begin_edit(qt_app, window, controller)
        replace_text(window.fields["title"], "Corrected song")
        labels = window.ordered_labels["artists"]
        labels.list.setCurrentRow(0)
        QTest.mouseClick(labels.remove_button, Qt.MouseButton.LeftButton)
        labels.name_edit.setText("Accept")
        QTest.mouseClick(labels.add_button, Qt.MouseButton.LeftButton)
        assert window.edit_dirty() and window.save_button.isEnabled()
        QTest.mouseClick(window.save_button, Qt.MouseButton.LeftButton)
        wait_until(qt_app, lambda: len(finished) == 1 and not controller._jobs)
        assert finished[0].entry.file_id == first.file_id
        assert window.current_file_id() == first.file_id
        assert window.fields["title"].text() == "Corrected song"
        assert window.fields["artists"].text() == "Accept"
        assert window.fields["title"].isReadOnly()
        row = window.model.row_for_file(first.file_id)
        assert "Corrected song" in str(window.model.data(window.model.index(row, 0)))
        assert read_entry(database, second.file_id) == second
        with closing(sqlite3.connect(database)) as connection:
            assert connection.execute("SELECT name FROM artists ORDER BY id").fetchall() == [
                ("Abbath",),
                ("Accept",),
            ]
            assert connection.execute(
                "SELECT value FROM raw_tags WHERE file_id=?", (first.file_id,)
            ).fetchone() == ("Abbath",)
    finally:
        teardown(window, controller)
    reopened, reader = create_window(preferences)
    try:
        open_ready(qt_app, reopened, reader, database, "Corrected song")
        assert reopened.fields["artists"].text() == "Accept"
        assert reader._session.database_path == database
    finally:
        teardown(reopened, reader)


def test_cancel_reloads_external_changes_without_saving_draft(qt_app, edit_catalog, tmp_path):
    database, first, _second = edit_catalog
    window, controller = create_window(CatalogPreferences(tmp_path / "settings.json"))
    try:
        open_ready(qt_app, window, controller, database)
        begin_edit(qt_app, window, controller)
        replace_text(window.fields["title"], "Discarded draft")
        with closing(sqlite3.connect(database)) as external, external:
            external.execute(
                "UPDATE tracks SET title='External correction' WHERE id=?", (first.track_id,)
            )
        QTest.mouseClick(window.cancel_edit_button, Qt.MouseButton.LeftButton)
        wait_until(
            qt_app,
            lambda: window.fields["title"].text() == "External correction" and not controller._jobs,
        )
        assert not window.edit_dirty()
        assert window.fields["title"].isReadOnly()
        assert read_entry(database, first.file_id).metadata.title == "External correction"
    finally:
        teardown(window, controller)


@pytest.mark.parametrize(
    "answer", [QMessageBox.StandardButton.Discard, QMessageBox.StandardButton.Save]
)
def test_selection_guard_discards_or_saves_before_navigation(
    qt_app, edit_catalog, tmp_path, monkeypatch, answer
):
    database, first, second = edit_catalog
    window, controller = create_window(CatalogPreferences(tmp_path / "settings.json"))
    monkeypatch.setattr(controller, "_confirm_unsaved", lambda: answer)
    try:
        open_ready(qt_app, window, controller, database)
        begin_edit(qt_app, window, controller)
        replace_text(window.fields["title"], "Guarded correction")
        window.table.selectRow(window.model.row_for_file(second.file_id))
        wait_until(
            qt_app,
            lambda: (
                window.current_file_id() == second.file_id
                and window.fields["title"].text() == "Sibling"
                and not controller._jobs
            ),
        )
        expected = "Guarded correction" if answer == QMessageBox.StandardButton.Save else "Original"
        assert read_entry(database, first.file_id).metadata.title == expected
        assert not window.edit_dirty()
    finally:
        teardown(window, controller)


def test_real_unsaved_dialog_cancel_restores_selection_and_draft(qt_app, edit_catalog, tmp_path):
    database, first, second = edit_catalog
    window, controller = create_window(CatalogPreferences(tmp_path / "settings.json"))
    seen = []
    try:
        open_ready(qt_app, window, controller, database)
        begin_edit(qt_app, window, controller)
        replace_text(window.fields["title"], "Kept draft")

        def cancel_dialog():
            dialogs = window.findChildren(QMessageBox)
            if not dialogs:
                QTimer.singleShot(5, cancel_dialog)
                return
            dialog = dialogs[-1]
            # QMessageBox ignores window titles on macOS; its message is portable.
            seen.append(dialog.text())
            dialog.button(QMessageBox.StandardButton.Cancel).click()

        QTimer.singleShot(0, cancel_dialog)
        window.table.selectRow(window.model.row_for_file(second.file_id))
        assert seen == ["Hay cambios sin guardar en esta canción."]
        assert window.current_file_id() == first.file_id
        assert window.fields["title"].text() == "Kept draft"
        assert window.edit_dirty()
        assert read_entry(database, first.file_id).metadata.title == "Original"
    finally:
        teardown(window, controller)


def test_conflict_keeps_draft_and_cancel_recovers_latest_record(qt_app, edit_catalog, tmp_path):
    database, first, _second = edit_catalog
    window, controller = create_window(CatalogPreferences(tmp_path / "settings.json"))
    results = []
    controller.edit_finished.connect(results.append)
    try:
        open_ready(qt_app, window, controller, database)
        begin_edit(qt_app, window, controller)
        replace_text(window.fields["title"], "Stale draft")
        with closing(sqlite3.connect(database)) as external, external:
            external.execute(
                "UPDATE tracks SET title='New external value' WHERE id=?", (first.track_id,)
            )
        QTest.mouseClick(window.save_button, Qt.MouseButton.LeftButton)
        wait_until(qt_app, lambda: len(results) == 1 and not controller._jobs)
        assert results == [None]
        assert window.fields["title"].text() == "Stale draft"
        assert window.edit_dirty() and window.save_button.isEnabled()
        assert "cambiaron" in window.error_label.text()
        assert read_entry(database, first.file_id).metadata.title == "New external value"
        QTest.mouseClick(window.cancel_edit_button, Qt.MouseButton.LeftButton)
        wait_until(
            qt_app,
            lambda: window.fields["title"].text() == "New external value" and not controller._jobs,
        )
    finally:
        teardown(window, controller)


@pytest.mark.parametrize("action", ["refresh", "open", "import", "close"])
def test_cancel_unsaved_guard_prevents_other_actions(
    qt_app, edit_catalog, tmp_path, monkeypatch, action
):
    database, first, _second = edit_catalog
    window, controller = create_window(CatalogPreferences(tmp_path / "settings.json"))
    confirmations = []

    def cancel():
        confirmations.append(action)
        return QMessageBox.StandardButton.Cancel

    monkeypatch.setattr(controller, "_confirm_unsaved", cancel)
    try:
        open_ready(qt_app, window, controller, database)
        begin_edit(qt_app, window, controller)
        replace_text(window.fields["title"], "Protected draft")
        if action == "refresh":
            controller.refresh()
        elif action == "open":
            controller.open_database(tmp_path / "missing.tfo")
        elif action == "import":
            music = tmp_path / "empty music"
            music.mkdir()
            controller.start_import(ImportRequest(music, tmp_path / "new.tfo", "create"))
        else:
            assert not window.close()
            assert window.isVisible()
        assert confirmations == [action]
        assert not controller._jobs and not controller.importing
        assert window.current_file_id() == first.file_id
        assert window.fields["title"].text() == "Protected draft"
        assert window.edit_dirty()
        assert read_entry(database, first.file_id).metadata.title == "Original"
        assert not (tmp_path / "missing.tfo").exists()
        assert not (tmp_path / "new.tfo").exists()
    finally:
        teardown(window, controller)


@pytest.mark.parametrize(
    "action,answer",
    [
        ("refresh", QMessageBox.StandardButton.Save),
        ("open", QMessageBox.StandardButton.Discard),
        ("import", QMessageBox.StandardButton.Save),
        ("close", QMessageBox.StandardButton.Save),
    ],
)
def test_unsaved_guard_continues_requested_action_after_save_or_discard(
    qt_app, edit_catalog, tmp_path, monkeypatch, action, answer
):
    database, first, _second = edit_catalog
    window, controller = create_window(CatalogPreferences(tmp_path / "settings.json"))
    monkeypatch.setattr(controller, "_confirm_unsaved", lambda: answer)
    finished = []
    imports = []
    closed = QSignalSpy(window.closing)
    controller.edit_finished.connect(finished.append)
    controller.import_finished.connect(imports.append)
    try:
        open_ready(qt_app, window, controller, database)
        begin_edit(qt_app, window, controller)
        replace_text(window.fields["title"], "Continued correction")
        if action == "refresh":
            controller.refresh()
            wait_until(
                qt_app,
                lambda: bool(finished) and not controller._jobs and not window.edit_dirty(),
            )
            assert window.fields["title"].text() == "Continued correction"
        elif action == "open":
            other = tmp_path / "Other.tfo"
            migrate_database(other)
            engine = create_engine(other)
            try:
                SqliteCatalogRepository(engine).save(
                    replace(first.metadata, title="Other catalogue"),
                    tmp_path / "other music",
                    "other.flac",
                )
            finally:
                engine.dispose()
            controller.open_database(other)
            wait_until(
                qt_app,
                lambda: window.fields["title"].text() == "Other catalogue" and not controller._jobs,
            )
            assert not finished
            assert controller._session.database_path == other
        elif action == "import":
            music = tmp_path / "empty music"
            music.mkdir()
            controller.start_import(ImportRequest(music, database, "update"))
            wait_until(
                qt_app,
                lambda: bool(imports) and not controller._jobs and not controller.importing,
            )
            assert len(finished) == 1
            assert imports[0].total == 0
            assert window.fields["title"].text() == "Continued correction"
        else:
            assert not window.close()
            wait_until(qt_app, lambda: closed.count() == 1)
            assert len(finished) == 1
            assert controller._closed
        expected = (
            "Continued correction" if answer == QMessageBox.StandardButton.Save else "Original"
        )
        assert read_entry(database, first.file_id).metadata.title == expected
    finally:
        teardown(window, controller)


class GateEditSession:
    def __init__(self, owner, delegate):
        self.owner = owner
        self.delegate = delegate

    def __getattr__(self, name):
        return getattr(self.delegate, name)

    def apply_edit(self, original, patch):
        self.owner.started.set()
        assert self.owner.release.wait(5), "The test must release the edit worker"
        if self.owner.failure:
            raise CatalogEditError("Controlled edit failure")
        return self.delegate.apply_edit(original, patch)

    def close(self):
        self.delegate.close()
        self.owner.writer_closed.set()


class GateEditFactory:
    def __init__(self, failure=False):
        self.delegate = SqliteCatalogEditSessionFactory()
        self.failure = failure
        self.started = threading.Event()
        self.release = threading.Event()
        self.writer_closed = threading.Event()
        self.write_count = 0

    def open_reader(self, path):
        return self.delegate.open_reader(path)

    def open_writer(self, path):
        self.write_count += 1
        return GateEditSession(self, self.delegate.open_writer(path))


@pytest.mark.parametrize("failure", [False, True])
def test_close_during_save_stays_responsive_and_waits_for_writer(qt_app, edit_catalog, failure):
    database, first, _second = edit_catalog
    gate = GateEditFactory(failure)
    window = MainWindow()
    controller = CatalogController(window, open_catalog, edit_factory=gate)
    closed = QSignalSpy(window.closing)
    finished = []
    controller.edit_finished.connect(finished.append)
    try:
        open_ready(qt_app, window, controller, database)
        begin_edit(qt_app, window, controller)
        replace_text(window.fields["title"], "Slow correction")
        QTest.mouseClick(window.save_button, Qt.MouseButton.LeftButton)
        wait_until(qt_app, gate.started.is_set)
        assert controller.saving
        assert not window.save_button.isEnabled()
        assert not window.table.isEnabled()
        assert not window.close()
        assert window.isVisible() and closed.count() == 0
        responsive = []
        QTimer.singleShot(0, lambda: responsive.append(True))
        wait_until(qt_app, lambda: bool(responsive))
        assert not gate.release.is_set()
        assert gate.write_count == 1
        gate.release.set()
        wait_until(qt_app, lambda: len(finished) == 1)
        assert gate.writer_closed.is_set()
        if failure:
            assert finished == [None]
            assert window.isVisible() and closed.count() == 0
            assert window.edit_dirty()
            assert window.fields["title"].text() == "Slow correction"
            assert read_entry(database, first.file_id).metadata.title == "Original"
        else:
            wait_until(qt_app, lambda: closed.count() == 1)
            assert controller._closed and not controller._pool.activeThreadCount()
            assert not window.isVisible()
            assert read_entry(database, first.file_id).metadata.title == "Slow correction"
    finally:
        gate.release.set()
        teardown(window, controller)


def test_failed_save_abandons_navigation_continuation_and_keeps_selected_draft(
    qt_app, edit_catalog, monkeypatch
):
    database, first, second = edit_catalog
    gate = GateEditFactory(failure=True)
    gate.release.set()
    window = MainWindow()
    controller = CatalogController(window, open_catalog, edit_factory=gate)
    monkeypatch.setattr(controller, "_confirm_unsaved", lambda: QMessageBox.StandardButton.Save)
    results = []
    controller.edit_finished.connect(results.append)
    try:
        open_ready(qt_app, window, controller, database)
        begin_edit(qt_app, window, controller)
        replace_text(window.fields["title"], "Retained correction")
        window.table.selectRow(window.model.row_for_file(second.file_id))
        wait_until(qt_app, lambda: results == [None] and not controller._jobs)
        assert window.current_file_id() == first.file_id
        assert window.fields["title"].text() == "Retained correction"
        assert window.edit_dirty()
        assert read_entry(database, first.file_id).metadata.title == "Original"
        gate.failure = False
        QTest.mouseClick(window.save_button, Qt.MouseButton.LeftButton)
        wait_until(qt_app, lambda: len(results) == 2 and not controller._jobs)
        assert results[1] is not None
        assert window.current_file_id() == first.file_id
        assert window.fields["title"].text() == "Retained correction"
        assert read_entry(database, second.file_id) == second
    finally:
        gate.release.set()
        teardown(window, controller)


class DelayedReader:
    def __init__(self, owner, delegate):
        self.owner = owner
        self.delegate = delegate

    def __getattr__(self, name):
        return getattr(self.delegate, name)

    def get_editable(self, file_id):
        result = self.delegate.get_editable(file_id)
        if self.owner.delay_file == file_id:
            self.owner.started.set()
            assert self.owner.release.wait(5), "The test must release the old snapshot"
        return result

    def find_artists(self, query):
        result = self.delegate.find_artists(query)
        if query == self.owner.delay_query:
            self.owner.started.set()
            assert self.owner.release.wait(5), "The test must release old suggestions"
        return result


class DelayedReadFactory:
    def __init__(self, *, delay_file=None, delay_query=None):
        self.delegate = SqliteCatalogEditSessionFactory()
        self.delay_file = delay_file
        self.delay_query = delay_query
        self.started = threading.Event()
        self.release = threading.Event()

    def open_reader(self, path):
        return DelayedReader(self, self.delegate.open_reader(path))

    def open_writer(self, path):
        return self.delegate.open_writer(path)


def test_late_edit_snapshot_cannot_replace_another_song_draft(qt_app, edit_catalog):
    database, first, second = edit_catalog
    gate = DelayedReadFactory(delay_file=first.file_id)
    window = MainWindow()
    controller = CatalogController(window, open_catalog, edit_factory=gate)
    started = []
    controller.edit_started.connect(started.append)
    try:
        open_ready(qt_app, window, controller, database)
        controller.start_edit()
        wait_until(qt_app, gate.started.is_set)
        window.table.selectRow(window.model.row_for_file(second.file_id))
        wait_until(qt_app, lambda: window.fields["title"].text() == "Sibling")
        controller.start_edit()
        wait_until(qt_app, lambda: started == [second.file_id])
        replace_text(window.fields["title"], "Second draft")
        gate.release.set()
        wait_until(qt_app, lambda: not controller._jobs)
        assert started == [second.file_id]
        assert window.current_file_id() == second.file_id
        assert window.fields["title"].text() == "Second draft"
        assert window.ordered_labels["artists"].names() == ("Accept",)
        assert window.edit_dirty()
    finally:
        gate.release.set()
        teardown(window, controller)


def test_late_suggestions_do_not_replace_latest_choices_or_dirty_draft(qt_app, edit_catalog):
    database, _first, _second = edit_catalog
    gate = DelayedReadFactory(delay_query="Ab")
    window = MainWindow()
    controller = CatalogController(window, open_catalog, edit_factory=gate)
    try:
        open_ready(qt_app, window, controller, database)
        begin_edit(qt_app, window, controller)
        replace_text(window.fields["title"], "Draft while searching")
        controller.find_suggestions("artists", "Ab")
        wait_until(qt_app, gate.started.is_set)
        controller.find_suggestions("artists", "Ac")
        suggestions = window.ordered_labels["artists"]._suggestions
        wait_until(qt_app, lambda: suggestions.stringList() == ["Accept"])
        gate.release.set()
        wait_until(qt_app, lambda: not controller._jobs)
        assert suggestions.stringList() == ["Accept"]
        assert window.ordered_labels["artists"].names() == ("Abbath",)
        assert window.fields["title"].text() == "Draft while searching"
        assert window.edit_dirty()
    finally:
        gate.release.set()
        teardown(window, controller)


def test_old_catalogue_snapshot_cannot_replace_draft_in_new_catalogue(
    qt_app, edit_catalog, tmp_path
):
    database, first, _second = edit_catalog
    other = tmp_path / "Other catálogo %.tfo"
    migrate_database(other)
    engine = create_engine(other)
    try:
        entry = SqliteCatalogRepository(engine).save(
            replace(first.metadata, title="Other catalogue"),
            tmp_path / "other missing music",
            "other.flac",
        )
    finally:
        engine.dispose()
    gate = DelayedReadFactory(delay_file=first.file_id)
    window = MainWindow()
    controller = CatalogController(window, open_catalog, edit_factory=gate)
    edits = []
    controller.edit_started.connect(edits.append)
    try:
        open_ready(qt_app, window, controller, database)
        controller.start_edit()
        wait_until(qt_app, gate.started.is_set)
        gate.delay_file = None
        controller.open_database(other)
        wait_until(qt_app, lambda: window.fields["title"].text() == "Other catalogue")
        controller.start_edit()
        wait_until(qt_app, lambda: edits == [entry.file_id])
        replace_text(window.fields["title"], "New catalogue draft")
        gate.release.set()
        wait_until(qt_app, lambda: not controller._jobs)
        assert controller._edit_path == other
        assert window.fields["title"].text() == "New catalogue draft"
        assert window.edit_dirty()
        assert edits == [entry.file_id]
        assert read_entry(database, first.file_id).metadata.title == "Original"
        assert read_entry(other, entry.file_id).metadata.title == "Other catalogue"
    finally:
        gate.release.set()
        teardown(window, controller)


class DelayedSummarySession:
    def __init__(self, gate, delegate):
        self.gate = gate
        self.delegate = delegate

    def __getattr__(self, name):
        return getattr(self.delegate, name)

    def list_summaries(self):
        result = self.delegate.list_summaries()
        if self.gate.delay:
            self.gate.started.set()
            assert self.gate.release.wait(5), "The test must release the older refresh"
        return result


class SummaryGate:
    def __init__(self):
        self.delay = False
        self.started = threading.Event()
        self.release = threading.Event()

    def __call__(self, path):
        return DelayedSummarySession(self, open_catalog(path))


def test_refresh_started_before_edit_cannot_replace_draft_or_prompt_navigation(
    qt_app, edit_catalog, monkeypatch
):
    database, first, _second = edit_catalog
    gate = SummaryGate()
    window = MainWindow()
    controller = CatalogController(window, gate, edit_factory=SqliteCatalogEditSessionFactory())
    confirmations = []

    def cancel_unexpected_dialog():
        confirmations.append(True)
        return QMessageBox.StandardButton.Cancel

    monkeypatch.setattr(controller, "_confirm_unsaved", cancel_unexpected_dialog)
    started = []
    controller.edit_started.connect(started.append)
    try:
        open_ready(qt_app, window, controller, database)
        gate.delay = True
        controller.refresh()
        wait_until(qt_app, gate.started.is_set)
        controller.start_edit()
        wait_until(qt_app, lambda: started == [first.file_id])
        replace_text(window.fields["title"], "Protected from late refresh")
        gate.release.set()
        wait_until(qt_app, lambda: not controller._jobs)
        assert not confirmations
        assert window.current_file_id() == first.file_id
        assert window.fields["title"].text() == "Protected from late refresh"
        assert window.edit_dirty()
    finally:
        gate.release.set()
        teardown(window, controller)


def test_save_observer_opening_catalogue_supersedes_earlier_navigation_continuation(
    qt_app, edit_catalog, tmp_path, monkeypatch
):
    database, first, _second = edit_catalog
    destinations = []
    for name in ("Deferred B", "Observer C"):
        path = tmp_path / f"{name}.tfo"
        migrate_database(path)
        engine = create_engine(path)
        try:
            entry = SqliteCatalogRepository(engine).save(
                replace(first.metadata, title=name), tmp_path / name, "01.flac"
            )
        finally:
            engine.dispose()
        assert entry.file_id == first.file_id
        destinations.append(path)
    deferred, observer_destination = destinations
    window, controller = create_window(CatalogPreferences(tmp_path / "settings.json"))
    monkeypatch.setattr(controller, "_confirm_unsaved", lambda: QMessageBox.StandardButton.Save)
    outcomes = []

    def open_from_observer(outcome):
        outcomes.append(outcome)
        if outcome is not None:
            controller.open_database(observer_destination)

    controller.edit_finished.connect(open_from_observer)
    try:
        open_ready(qt_app, window, controller, database)
        begin_edit(qt_app, window, controller)
        replace_text(window.fields["title"], "Saved before observer")
        controller.open_database(deferred)
        wait_until(
            qt_app,
            lambda: (
                bool(outcomes)
                and not controller._jobs
                and window.fields["title"].text() != "Saved before observer"
            ),
        )
        assert controller._session.database_path == observer_destination
        assert window.fields["title"].text() == "Observer C"
        assert window.current_file_id() == first.file_id
        assert read_entry(database, first.file_id).metadata.title == "Saved before observer"
        assert read_entry(deferred, first.file_id).metadata.title == "Deferred B"
        assert read_entry(observer_destination, first.file_id).metadata.title == "Observer C"
    finally:
        teardown(window, controller)


def test_legacy_draft_invalid_save_and_cancel_do_not_migrate_then_valid_save_backs_up(
    qt_app, tmp_path
):
    database = tmp_path / "legacy editable %.tfo"
    legacy_catalog(database, tmp_path / "missing music")
    before = database.read_bytes()
    gate = GateEditFactory()
    gate.release.set()
    window = MainWindow()
    controller = CatalogController(window, open_catalog, edit_factory=gate)
    finished = []
    controller.edit_finished.connect(finished.append)
    try:
        open_ready(qt_app, window, controller, database)
        begin_edit(qt_app, window, controller)
        assert database.read_bytes() == before
        replace_text(window.fields["track_number"], "0")
        assert not window.save_button.isEnabled()
        assert window.field_errors["track_number"].text()
        controller.save_edit()
        assert gate.write_count == 0
        assert not finished
        assert database.read_bytes() == before
        assert not list(tmp_path.glob("*.bak"))
        QTest.mouseClick(window.cancel_edit_button, Qt.MouseButton.LeftButton)
        wait_until(qt_app, lambda: not controller._jobs)
        begin_edit(qt_app, window, controller)
        replace_text(window.fields["title"], "Legacy GUI correction")
        QTest.mouseClick(window.save_button, Qt.MouseButton.LeftButton)
        wait_until(qt_app, lambda: len(finished) == 1 and not controller._jobs)
        assert gate.write_count == 1
        assert finished[0].backup_path is not None
        assert str(finished[0].backup_path) in window.status_label.text()
        with closing(sqlite3.connect(finished[0].backup_path)) as backup:
            assert backup.execute("SELECT version_num FROM alembic_version").fetchone() == (
                "001_initial",
            )
        assert read_entry(database, 1).metadata.title == "Legacy GUI correction"
    finally:
        gate.release.set()
        teardown(window, controller)
