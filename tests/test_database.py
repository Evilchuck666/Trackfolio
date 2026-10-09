"""Persistence checks against actual SQLite databases and the exported migration."""

import sqlite3
from pathlib import Path

import pytest
from alembic import command
from sqlalchemy import inspect, select
from sqlalchemy.exc import IntegrityError

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


def test_export_matches_migrated_schema_and_committed_artifact(tmp_path):
    engine = catalogue(tmp_path)
    exported = db.initial_schema_sql()
    assert exported == (Path(__file__).parents[1] / "migrations/001_initial.sql").read_text(
        encoding="utf-8"
    )
    offline_path = tmp_path / "offline.sqlite3"
    try:
        with sqlite3.connect(offline_path) as offline:
            offline.executescript(exported)
            assert offline.execute("PRAGMA foreign_keys").fetchone()[0] == 1
            assert offline.execute("SELECT version_num FROM alembic_version").fetchone() == (
                "001_initial",
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
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE other_application (value TEXT)")
        connection.execute("INSERT INTO other_application VALUES ('keep me')")
    with pytest.raises(db.UnknownDatabaseError, match="no se adoptan"):
        db.migrate_database(path)
    with sqlite3.connect(path) as connection:
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
