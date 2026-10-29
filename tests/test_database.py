"""Persistence checks against actual SQLite databases and the exported migration."""

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path
from threading import Barrier, local

import pytest
from alembic import command
from sqlalchemy import inspect, select
from sqlalchemy.exc import IntegrityError, OperationalError

from trackfolio.infrastructure import database as db


def catalogue(tmp_path):
    path = tmp_path / "catálogo % portable.tfo"
    db.migrate_database(path)
    return db.create_engine(path)


def schema_rows(connection):
    rows = connection.exec_driver_sql(
        "SELECT type, name, sql FROM sqlite_schema "
        "WHERE name NOT LIKE 'sqlite_%' ORDER BY type, name"
    ).all()
    # Alembic's offline output expands DDL tabs; compare schema, not indentation.
    return [(kind, name, " ".join(sql.split()) if sql else None) for kind, name, sql in rows]


@pytest.mark.parametrize(
    "revision,exporter,artifact",
    [
        (db.LEGACY_REVISION, db.initial_schema_sql, "001_initial.sql"),
        (db.REVISION, db.current_schema_sql, "002_current.sql"),
    ],
)
def test_exports_match_their_revision_and_committed_artifact(
    tmp_path, revision, exporter, artifact
):
    engine = db.create_engine(tmp_path / "online.sqlite3")
    with engine.begin() as connection:
        config = db.migration_config()
        config.attributes["connection"] = connection
        command.upgrade(config, revision)
    exported = exporter()
    assert exported == (Path(__file__).parents[1] / "migrations" / artifact).read_text(
        encoding="utf-8"
    )
    offline_path = tmp_path / "offline.sqlite3"
    try:
        with closing(sqlite3.connect(offline_path)) as offline, offline:
            offline.executescript(exported)
            assert offline.execute("PRAGMA foreign_keys").fetchone()[0] == 1
            assert offline.execute("SELECT version_num FROM alembic_version").fetchone() == (
                revision,
            )
        offline_engine = db.create_engine(offline_path)
        try:
            with engine.connect() as online, offline_engine.connect() as offline:
                assert schema_rows(online) == schema_rows(offline)
                assert online.exec_driver_sql("PRAGMA application_id").scalar_one() == (
                    offline.exec_driver_sql("PRAGMA application_id").scalar_one()
                )
        finally:
            offline_engine.dispose()
        db.migrate_database(offline_path)
    finally:
        engine.dispose()


def legacy_catalog(path):
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.executescript(db.initial_schema_sql())
        connection.execute("INSERT INTO artists (id, name) VALUES (1, 'Accept'), (2, 'Accept')")
        connection.execute("INSERT INTO tracks (id, title) VALUES (1, 'Preserved')")
        connection.execute(
            "INSERT INTO track_artists (track_id, position, artist_id) VALUES (1, 0, 2)"
        )


def test_legacy_catalog_releases_its_connection(tmp_path, monkeypatch):
    connect = sqlite3.connect
    connections = []

    def record_connection(*args, **kwargs):
        connection = connect(*args, **kwargs)
        connections.append(connection)
        return connection

    monkeypatch.setattr(sqlite3, "connect", record_connection)
    legacy_catalog(tmp_path / "legacy.tfo")
    assert len(connections) == 1
    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
        connections[0].execute("SELECT 1")


def test_upgrade_backs_up_legacy_data_and_is_idempotent(tmp_path):
    path = tmp_path / "catálogo %.tfo"
    legacy_catalog(path)
    backup = db.upgrade_database(path)
    assert backup is not None and backup.parent == path.parent
    assert backup.name.startswith(f"{path.name}.{db.LEGACY_REVISION}.")
    with closing(sqlite3.connect(backup)) as saved, saved:
        assert saved.execute("SELECT version_num FROM alembic_version").fetchone() == (
            db.LEGACY_REVISION,
        )
        assert saved.execute("SELECT id, name FROM artists ORDER BY id").fetchall() == [
            (1, "Accept"),
            (2, "Accept"),
        ]
        assert saved.execute("SELECT artist_id FROM track_artists").fetchone() == (2,)
    with closing(sqlite3.connect(path)) as current, current:
        assert current.execute("SELECT version_num FROM alembic_version").fetchone() == (
            db.REVISION,
        )
        assert current.execute("SELECT id, name FROM artists").fetchall() == [(1, "Accept")]
        assert current.execute("SELECT artist_id FROM track_artists").fetchone() == (1,)
    before = path.read_bytes()
    assert db.upgrade_database(path) is None
    assert db.migrate_database(path) is None
    assert path.read_bytes() == before
    assert list(tmp_path.glob("*.bak")) == [backup]


def test_backup_includes_committed_wal_pages(tmp_path):
    path = tmp_path / "wal.tfo"
    legacy_catalog(path)
    writer = sqlite3.connect(path, autocommit=True)
    try:
        assert writer.execute("PRAGMA journal_mode=WAL").fetchone() == ("wal",)
        writer.execute("INSERT INTO artists (id, name) VALUES (3, 'In WAL')")
        assert path.with_name(path.name + "-wal").exists()
        backup = db.upgrade_database(path)
        assert backup is not None
        with closing(sqlite3.connect(backup)) as saved, saved:
            assert saved.execute("SELECT name FROM artists WHERE id=3").fetchone() == ("In WAL",)
            assert saved.execute("PRAGMA integrity_check").fetchone() == ("ok",)
    finally:
        writer.close()


def test_simultaneous_upgrades_share_one_backup_and_recheck_after_writer_lock(
    tmp_path, monkeypatch
):
    path = tmp_path / "parallel.tfo"
    legacy_catalog(path)
    check = db._check_database
    rendezvous = Barrier(2)
    worker = local()

    def synchronized_check(connection):
        revision = check(connection)
        if not getattr(worker, "checked", False):
            worker.checked = True
            assert revision == db.LEGACY_REVISION
            rendezvous.wait(timeout=5)
        return revision

    monkeypatch.setattr(db, "_check_database", synchronized_check)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(db.upgrade_database, path) for _ in range(2)]
        backups = [future.result(timeout=10) for future in futures]
    assert sum(backup is not None for backup in backups) == 1
    assert len(list(tmp_path.glob("*.bak"))) == 1
    with closing(sqlite3.connect(path)) as current, current:
        assert current.execute("SELECT version_num FROM alembic_version").fetchone() == (
            db.REVISION,
        )
        assert current.execute("SELECT id, name FROM artists").fetchall() == [(1, "Accept")]


def test_backup_failure_leaves_legacy_catalog_unchanged(tmp_path, monkeypatch):
    path = tmp_path / "backup-failure.tfo"
    legacy_catalog(path)
    before = path.read_bytes()

    def fail_backup(_path):
        raise OSError("simulated backup failure")

    monkeypatch.setattr(db, "_backup_database", fail_backup)
    with pytest.raises(OSError, match="backup failure"):
        db.upgrade_database(path)
    assert path.read_bytes() == before
    assert not list(tmp_path.glob("*.bak"))


def test_failed_backup_removes_only_its_reserved_output(tmp_path, monkeypatch):
    path = tmp_path / "backup-failure.tfo"
    legacy_catalog(path)
    foreign_backup = tmp_path / "other.bak"
    foreign_backup.write_bytes(b"preserve")
    original_connect = sqlite3.connect
    count = 0

    def fail_destination(*args, **kwargs):
        nonlocal count
        count += 1
        if count == 2:
            raise OSError("simulated destination failure")
        return original_connect(*args, **kwargs)

    monkeypatch.setattr(db.sqlite3, "connect", fail_destination)
    with pytest.raises(OSError, match="destination failure"):
        db._backup_database(path)
    assert list(tmp_path.glob("*.bak")) == [foreign_backup]
    assert foreign_backup.read_bytes() == b"preserve"


def test_failed_legacy_upgrade_keeps_valid_backup_and_rolls_back(tmp_path, monkeypatch):
    path = tmp_path / "rollback.tfo"
    legacy_catalog(path)
    before = path.read_bytes()
    upgrade = command.upgrade

    def fail_after_upgrade(config, revision):
        upgrade(config, revision)
        raise RuntimeError("simulated upgrade failure")

    monkeypatch.setattr(command, "upgrade", fail_after_upgrade)
    with pytest.raises(RuntimeError, match="upgrade failure"):
        db.upgrade_database(path)
    assert path.read_bytes() == before
    [backup] = tmp_path.glob("*.bak")
    with closing(sqlite3.connect(backup)) as saved, saved:
        assert saved.execute("SELECT count(*) FROM artists").fetchone() == (2,)
        assert saved.execute("SELECT version_num FROM alembic_version").fetchone() == (
            db.LEGACY_REVISION,
        )


@pytest.mark.parametrize("kind", ["missing", "empty", "directory"])
def test_explicit_upgrade_only_accepts_existing_catalogs(tmp_path, kind):
    path = tmp_path / "new directory" / "catalog.tfo"
    if kind == "empty":
        path.parent.mkdir()
        path.touch()
    elif kind == "directory":
        path.mkdir(parents=True)
    before = set(tmp_path.rglob("*"))
    with pytest.raises((FileNotFoundError, ValueError)):
        db.upgrade_database(path)
    assert set(tmp_path.rglob("*")) == before


def test_existing_migration_target_disappearing_is_not_recreated(tmp_path, monkeypatch):
    path = tmp_path / "disappeared.tfo"
    legacy_catalog(path)
    original = db.writable_engine

    def vanished(database):
        database.unlink()
        return original(database)

    monkeypatch.setattr(db, "writable_engine", vanished)
    with pytest.raises(OperationalError, match="unable to open"):
        db.migrate_database(path)
    assert not path.exists()


def test_missing_tags_remain_null_in_readable_view(tmp_path):
    engine = catalogue(tmp_path)
    try:
        with engine.begin() as connection:
            connection.execute(db.libraries.insert(), {"id": 1, "root_path": "/library"})
            connection.execute(
                db.albums.insert(),
                {"id": 1, "library_id": 1, "directory": ".", "import_key": "a", "disc_total": 3},
            )
            connection.execute(db.tracks.insert(), {"id": 1, "album_id": 1})
            connection.execute(
                db.audio_files.insert(),
                {
                    "id": 1,
                    "library_id": 1,
                    "relative_path": "untagged.flac",
                    "track_id": 1,
                    "format": "FLAC",
                    "duration_seconds": 0.0,
                },
            )
            row = connection.exec_driver_sql("SELECT * FROM track_details").mappings().one()
            for field in (
                "title",
                "album",
                "album_year",
                "album_date",
                "track_number",
                "track_total",
                "disc_number",
                "disc_total",
                "artists",
                "album_artists",
                "genres",
                "lyrics",
                "cover_source",
                "cover_mime",
                "cover_bytes",
            ):
                assert row[field] is None, field
            assert row["duration_seconds"] == 0.0
    finally:
        engine.dispose()


def test_view_preserves_order_without_join_fanout_or_blob_column(tmp_path):
    engine = catalogue(tmp_path)
    try:
        with engine.begin() as connection:
            connection.execute(db.libraries.insert(), {"id": 1, "root_path": "file:///library"})
            connection.execute(db.tracks.insert(), {"id": 1, "title": "Song"})
            connection.execute(
                db.artists.insert(),
                [{"id": 1, "name": "Last"}, {"id": 2, "name": "First"}],
            )
            connection.execute(
                db.track_artists.insert(),
                [
                    {"track_id": 1, "artist_id": 1, "position": 1},
                    {"track_id": 1, "artist_id": 2, "position": 0},
                ],
            )
            connection.execute(
                db.genres.insert(), [{"id": 1, "name": "Rock"}, {"id": 2, "name": "Jazz"}]
            )
            connection.execute(
                db.track_genres.insert(),
                [
                    {"track_id": 1, "genre_id": 1, "position": 1},
                    {"track_id": 1, "genre_id": 2, "position": 0},
                ],
            )
            connection.execute(
                db.artworks.insert(),
                {"id": 1, "sha256": "a" * 64, "data": b"image", "mime": "image/jpeg"},
            )
            connection.execute(
                db.audio_files.insert(),
                {
                    "id": 1,
                    "library_id": 1,
                    "relative_path": "song.mp3",
                    "track_id": 1,
                    "format": "MP3",
                    "cover_artwork_id": 1,
                    "cover_source": "embedded",
                },
            )
            rows = connection.exec_driver_sql("SELECT * FROM track_details").mappings().all()
            assert len(rows) == 1
            assert rows[0]["artists"] == "First; Last"
            assert rows[0]["genres"] == "Jazz; Rock"
            assert rows[0]["cover_mime"] == "image/jpeg"
            assert rows[0]["cover_bytes"] == 5
            assert "data" not in rows[0]
    finally:
        engine.dispose()


@pytest.mark.parametrize(
    "column,value",
    [("track_number", 0), ("track_total", -1), ("disc_number", "text"), ("disc_total", 0)],
)
def test_positive_integer_constraints_reject_invalid_track_values(tmp_path, column, value):
    engine = catalogue(tmp_path)
    try:
        with pytest.raises(IntegrityError), engine.begin() as connection:
            connection.execute(db.tracks.insert(), {column: value})
    finally:
        engine.dispose()


def test_foreign_keys_on_every_connection_and_transactions_roll_back(tmp_path):
    engine = catalogue(tmp_path)
    try:
        with engine.connect() as first, engine.connect() as second:
            assert first.exec_driver_sql("PRAGMA foreign_keys").scalar_one() == 1
            assert second.exec_driver_sql("PRAGMA foreign_keys").scalar_one() == 1
        with pytest.raises(IntegrityError), engine.begin() as connection:
            connection.execute(db.libraries.insert(), {"id": 1, "root_path": "/library"})
            connection.execute(
                db.audio_files.insert(),
                {
                    "library_id": 1,
                    "relative_path": "orphan.flac",
                    "track_id": 123,
                    "format": "FLAC",
                },
            )
        with engine.connect() as connection:
            assert connection.execute(select(db.libraries.c.id)).all() == []
    finally:
        engine.dispose()


def test_cover_with_unknown_source_is_rejected(tmp_path):
    engine = catalogue(tmp_path)
    try:
        with engine.begin() as connection:
            connection.execute(db.libraries.insert(), {"id": 1, "root_path": "/library"})
            connection.execute(db.tracks.insert(), {"id": 1})
            connection.execute(
                db.artworks.insert(),
                {"id": 1, "sha256": "a" * 64, "data": b"image", "mime": "image/jpeg"},
            )
        with pytest.raises(IntegrityError), engine.begin() as connection:
            connection.execute(
                db.audio_files.insert(),
                {
                    "library_id": 1,
                    "relative_path": "song.flac",
                    "track_id": 1,
                    "format": "FLAC",
                    "cover_artwork_id": 1,
                    "cover_source": None,
                },
            )
    finally:
        engine.dispose()


def test_failed_migration_rolls_back_ddl_and_stamp(tmp_path, monkeypatch):
    path = tmp_path / "failed.sqlite3"
    upgrade = command.upgrade

    def fail_after_creation(config, revision):
        upgrade(config, revision)
        raise RuntimeError("simulated migration failure")

    monkeypatch.setattr(command, "upgrade", fail_after_creation)
    with pytest.raises(RuntimeError, match="simulated"):
        db.migrate_database(path)
    engine = db.create_engine(path)
    try:
        with engine.connect() as connection:
            assert inspect(connection).get_table_names() == []
            assert inspect(connection).get_view_names() == []
            assert connection.exec_driver_sql("PRAGMA application_id").scalar_one() == 0
    finally:
        engine.dispose()


def test_unknown_database_is_not_adopted_or_changed(tmp_path):
    path = tmp_path / "foreign.sqlite3"
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.execute("CREATE TABLE other_application (value TEXT)")
        connection.execute("INSERT INTO other_application VALUES ('keep me')")
    with pytest.raises(db.UnknownDatabaseError, match="no se adoptan"):
        db.migrate_database(path)
    with closing(sqlite3.connect(path)) as connection, connection:
        assert connection.execute("SELECT value FROM other_application").fetchone() == ("keep me",)
        assert connection.execute(
            "SELECT count(*) FROM sqlite_schema WHERE type = 'table'"
        ).fetchone() == (1,)


def test_downgrade_to_base_then_upgrade_and_idempotent_existing_data(tmp_path):
    path = tmp_path / "revision.sqlite3"
    db.migrate_database(path)
    engine = db.create_engine(path)
    try:
        with engine.begin() as connection:
            config = db.migration_config()
            config.attributes["connection"] = connection
            command.downgrade(config, "base")
        with engine.connect() as connection:
            assert inspect(connection).get_table_names() == ["alembic_version"]
            assert inspect(connection).get_view_names() == []
        db.migrate_database(path)
        with engine.begin() as connection:
            connection.execute(db.libraries.insert(), {"id": 1, "root_path": "/keep"})
        db.migrate_database(path)
        with engine.connect() as connection:
            assert connection.execute(select(db.libraries.c.root_path)).one() == ("/keep",)
    finally:
        engine.dispose()
