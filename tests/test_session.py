"""Opening a catalog for the GUI never creates, migrates or writes a database."""

import os
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import PureWindowsPath

import pytest
from sqlalchemy.exc import DatabaseError, OperationalError

from trackfolio.application.catalog import CatalogAccessError, GetTrack, ListTrackSummaries
from trackfolio.domain.metadata import Artwork, TrackMetadata
from trackfolio.infrastructure.catalog import SqliteCatalogRepository
from trackfolio.infrastructure.database import UnknownDatabaseError, create_engine, migrate_database
from trackfolio.infrastructure.session import _file_uri, open_catalog


def build_catalog(path):
    migrate_database(path)
    engine = create_engine(path)
    try:
        return SqliteCatalogRepository(engine).save(
            TrackMetadata(
                title="Título",
                artists=("Dos", "Uno"),
                album="Álbum",
                album_year=1981,
                artwork=Artwork(b"cover stored in the database", "image/jpeg"),
                audio_format="flac",
            ),
            path.parent,
            "Song.flac",
        )
    finally:
        engine.dispose()


@pytest.mark.parametrize(
    "name",
    [
        "catálogo con espacios.tfo",
        "catálogo % #.tfo",
        "catálogo con espacios.sqlite3",
        "catálogo % #.sqlite3",
    ],
)
def test_open_reads_from_database_with_portable_paths_and_does_not_modify_it(tmp_path, name):
    path = tmp_path / name
    entry = build_catalog(path)
    before = path.read_bytes()
    files_before = set(tmp_path.iterdir())
    session = open_catalog(path)
    try:
        assert session.database_path == path.resolve()
        assert GetTrack(session).execute(entry.file_id) == entry
        summaries = ListTrackSummaries(session).execute()
        assert len(summaries) == 1
        assert summaries[0].artists == ("Dos", "Uno")
        assert summaries[0].album_year == 1981
        assert session.get(99999) is None
        # The source music file is deliberately absent: only DB content is needed.
        assert not (path.parent / "Song.flac").exists()
    finally:
        session.close()
    assert path.read_bytes() == before
    assert set(tmp_path.iterdir()) == files_before


@pytest.mark.skipif(os.name == "nt", reason="Question mark is not a valid Windows filename")
def test_uri_escapes_question_mark_without_selecting_a_different_database(tmp_path):
    path = tmp_path / "catálogo ?.sqlite3"
    entry = build_catalog(path)
    session = open_catalog(path)
    try:
        assert session.get(entry.file_id) == entry
    finally:
        session.close()


def test_session_database_connections_reject_writes(tmp_path):
    path = tmp_path / "readonly.sqlite3"
    build_catalog(path)
    before = path.read_bytes()
    session = open_catalog(path)
    try:
        # The infrastructure session does not expose mutations in its public contract.
        with session._engine.connect() as connection:
            assert connection.exec_driver_sql("PRAGMA busy_timeout").scalar_one() == 2000
        with (
            pytest.raises(OperationalError, match="readonly"),
            session._engine.begin() as connection,
        ):
            connection.exec_driver_sql("UPDATE tracks SET title = 'Should not be saved'")
    finally:
        session.close()
    assert path.read_bytes() == before


def test_session_uses_connections_safely_across_worker_threads(tmp_path):
    path = tmp_path / "threads.sqlite3"
    entry = build_catalog(path)
    session = open_catalog(path)
    try:
        with ThreadPoolExecutor(max_workers=4) as workers:
            futures = [workers.submit(session.get, entry.file_id) for _ in range(8)]
            assert [future.result() for future in futures] == [entry] * 8
    finally:
        session.close()


def test_session_close_is_idempotent_and_reads_after_close_fail(tmp_path):
    path = tmp_path / "close.sqlite3"
    build_catalog(path)
    session = open_catalog(path)
    session.close()
    session.close()
    with pytest.raises(RuntimeError, match="cerrado"):
        session.get(1)
    with pytest.raises(RuntimeError, match="cerrado"):
        session.list_summaries()


def test_open_rejects_missing_file_without_creating_file_or_parents(tmp_path):
    path = tmp_path / "missing directory" / "catalog.sqlite3"
    with pytest.raises(FileNotFoundError):
        open_catalog(path)
    assert not path.parent.exists()


def test_open_rejects_a_directory(tmp_path):
    with pytest.raises(ValueError, match="archivo"):
        open_catalog(tmp_path)


@pytest.mark.parametrize("kind", ["empty", "foreign", "no-marker", "revision", "column", "view"])
def test_open_rejects_unrecognized_or_modified_schemas_without_adopting_them(tmp_path, kind):
    path = tmp_path / f"{kind}.sqlite3"
    if kind in {"empty", "foreign"}:
        with sqlite3.connect(path) as connection:
            if kind == "foreign":
                connection.execute("CREATE TABLE another_application (value TEXT)")
    else:
        build_catalog(path)
        with sqlite3.connect(path) as connection:
            if kind == "no-marker":
                connection.execute("PRAGMA application_id = 0")
            elif kind == "revision":
                connection.execute("UPDATE alembic_version SET version_num = 'future_revision'")
            elif kind == "column":
                connection.execute("ALTER TABLE tracks ADD COLUMN extra TEXT")
            elif kind == "view":
                connection.execute("DROP VIEW track_details")
                connection.execute("CREATE VIEW track_details AS SELECT id FROM tracks")
    before = path.read_bytes()
    with pytest.raises(UnknownDatabaseError, match="compatible"):
        open_catalog(path)
    assert path.read_bytes() == before


def test_open_rejects_non_sqlite_file_without_modifying_it(tmp_path):
    path = tmp_path / "not_sqlite.sqlite3"
    path.write_bytes(b"a file from another application")
    with pytest.raises(CatalogAccessError, match="SQLite válida") as error:
        open_catalog(path)
    assert isinstance(error.value.__cause__, DatabaseError)
    assert "PRAGMA" not in str(error.value)
    assert "sqlalchemy" not in str(error.value)
    assert path.read_bytes() == b"a file from another application"


@pytest.mark.parametrize("operation", ["open", "get", "list"])
def test_locked_catalog_reports_recoverable_message_and_can_be_retried(tmp_path, operation):
    path = tmp_path / "locked.sqlite3"
    entry = build_catalog(path)
    session = open_catalog(path) if operation != "open" else None
    try:
        with sqlite3.connect(path) as writer:
            writer.execute("BEGIN EXCLUSIVE")
            try:
                with pytest.raises(CatalogAccessError, match="ocupado") as error:
                    if operation == "open":
                        open_catalog(path)
                    elif operation == "get":
                        session.get(entry.file_id)
                    else:
                        session.list_summaries()
                assert isinstance(error.value.__cause__, OperationalError)
                assert "SELECT" not in str(error.value)
                assert "PRAGMA" not in str(error.value)
                assert "sqlalchemy" not in str(error.value)
            finally:
                writer.rollback()
        if session is None:
            session = open_catalog(path)
        assert session.get(entry.file_id) == entry
        assert len(session.list_summaries()) == 1
    finally:
        if session is not None:
            session.close()


@pytest.mark.parametrize(
    "path, expected",
    [
        (
            PureWindowsPath("C:/Música con espacios/catálogo % #.sqlite3"),
            "file:///C:/M%C3%BAsica%20con%20espacios/cat%C3%A1logo%20%25%20%23.sqlite3",
        ),
        (
            PureWindowsPath("//server/share/Música/catálogo %.sqlite3"),
            "file:////server/share/M%C3%BAsica/cat%C3%A1logo%20%25.sqlite3",
        ),
    ],
)
def test_windows_drive_and_unc_uri_encoding_on_every_platform(path, expected):
    assert _file_uri(path) == expected
