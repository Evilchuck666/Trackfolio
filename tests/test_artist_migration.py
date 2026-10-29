"""Artist consolidation on actual populated SQLite catalogues and offline SQL."""

import io
import sqlite3

import pytest
from alembic import command
from sqlalchemy import event, select
from sqlalchemy.exc import IntegrityError

from trackfolio.infrastructure import database as db
from trackfolio.infrastructure import schema
from trackfolio.infrastructure.migrations import initial_schema
from trackfolio.infrastructure.schema_validation import (
    UnknownDatabaseError,
    validate_catalog_connection,
)


def _upgrade(engine, revision):
    with engine.begin() as connection:
        config = db.migration_config()
        config.attributes["connection"] = connection
        command.upgrade(config, revision)


@pytest.fixture
def legacy_catalog(tmp_path):
    path = tmp_path / "artistas % antiguos.tfo"
    engine = db.create_engine(path)
    _upgrade(engine, schema.LEGACY_REVISION)
    with engine.begin() as connection:
        connection.execute(initial_schema.libraries.insert(), {"id": 1, "root_path": "/music"})
        connection.execute(
            initial_schema.albums.insert(),
            {"id": 10, "library_id": 1, "directory": "album", "import_key": "album", "title": "LP"},
        )
        connection.execute(
            initial_schema.tracks.insert(),
            [
                {"id": 20, "album_id": 10, "title": "First", "lyrics": "Original lyrics"},
                {"id": 21, "album_id": 10, "title": "Second", "lyrics": None},
            ],
        )
        connection.execute(
            initial_schema.artists.insert(),
            [
                {"id": 1, "name": "Abbath", "external_id": None},
                {"id": 2, "name": "Abbath", "external_id": "first-external"},
                {"id": 3, "name": "Accept", "external_id": "canonical-external"},
                {"id": 4, "name": "Accept", "external_id": "different-external"},
                {"id": 5, "name": "accept", "external_id": None},
                {"id": 6, "name": "Unused", "external_id": None},
                {"id": 7, "name": "Unused", "external_id": "unused-external"},
                {"id": 8, "name": "Guest", "external_id": None},
                {"id": 9, "name": "Abbath", "external_id": "later-external"},
            ],
        )
        connection.execute(
            initial_schema.track_artists.insert(),
            [
                {"track_id": 20, "role": "artist", "position": 0, "artist_id": 2},
                {"track_id": 20, "role": "artist", "position": 1, "artist_id": 9},
                {"track_id": 20, "role": "composer", "position": 0, "artist_id": 4},
                {"track_id": 21, "role": "artist", "position": 0, "artist_id": 5},
                {"track_id": 21, "role": "artist", "position": 1, "artist_id": 8},
            ],
        )
        connection.execute(
            initial_schema.album_artists.insert(),
            [
                {"album_id": 10, "role": "album_artist", "position": 0, "artist_id": 9},
                {"album_id": 10, "role": "album_artist", "position": 1, "artist_id": 4},
                {"album_id": 10, "role": "composer", "position": 0, "artist_id": 2},
            ],
        )
        connection.execute(initial_schema.genres.insert(), {"id": 30, "name": "Metal"})
        connection.execute(
            initial_schema.track_genres.insert(), {"track_id": 20, "position": 0, "genre_id": 30}
        )
        connection.execute(
            initial_schema.artworks.insert(),
            {"id": 40, "sha256": "a" * 64, "data": b"\x00\xfforiginal image", "mime": "image/png"},
        )
        connection.execute(
            initial_schema.audio_files.insert(),
            {
                "id": 50,
                "library_id": 1,
                "relative_path": "album/original.flac",
                "track_id": 20,
                "format": "FLAC",
                "duration_seconds": 120.25,
                "cover_artwork_id": 40,
                "cover_source": "embedded",
            },
        )
        connection.execute(
            initial_schema.raw_tags.insert(),
            [
                {"file_id": 50, "key": "ARTIST", "position": 0, "value": "Abbath"},
                {"file_id": 50, "key": "COMMENT", "position": 0, "value": " Unmodified raw tag "},
            ],
        )
    try:
        yield path, engine
    finally:
        engine.dispose()


def _rows(connection, table):
    return connection.execute(select(table).order_by(*table.primary_key.columns)).all()


def _snapshot(engine):
    with engine.connect() as connection:
        return {
            table.name: _rows(connection, table) for table in initial_schema.metadata.sorted_tables
        }


def test_current_metadata_does_not_change_the_frozen_initial_snapshot():
    assert schema.artists is not initial_schema.artists
    assert "uq_artists_name" not in {index.name for index in initial_schema.artists.indexes}
    assert "uq_artists_name" in {index.name for index in schema.artists.indexes}
    assert set(schema.metadata.tables) == set(initial_schema.metadata.tables)


def test_populated_legacy_catalogue_preserves_every_credit_and_unrelated_value(legacy_catalog):
    _, engine = legacy_catalog
    before = _snapshot(engine)
    with engine.connect() as connection:
        view_before = connection.exec_driver_sql("SELECT * FROM track_details").all()
        assert validate_catalog_connection(connection) == schema.LEGACY_REVISION
        with pytest.raises(UnknownDatabaseError, match="actualizarse"):
            validate_catalog_connection(connection, require_current=True)
    _upgrade(engine, schema.REVISION)
    after = _snapshot(engine)
    assert after["artists"] == [
        (1, "Abbath", "first-external"),
        (3, "Accept", "canonical-external"),
        (5, "accept", None),
        (6, "Unused", "unused-external"),
        (8, "Guest", None),
    ]
    canonical = {2: 1, 4: 3, 7: 6, 9: 1}
    for name in ("track_artists", "album_artists"):
        assert after[name] == [(*row[:-1], canonical.get(row[-1], row[-1])) for row in before[name]]
    for name in before.keys() - {"artists", "track_artists", "album_artists"}:
        assert after[name] == before[name], name
    with engine.connect() as connection:
        assert validate_catalog_connection(connection, require_current=True) == schema.REVISION
        assert connection.exec_driver_sql("SELECT * FROM track_details").all() == view_before
        assert connection.exec_driver_sql("PRAGMA foreign_key_check").all() == []
        assert connection.exec_driver_sql("PRAGMA integrity_check").scalar_one() == "ok"
        assert "ix_artists_name_consolidation" not in {
            row["name"]
            for row in connection.exec_driver_sql("PRAGMA index_list('artists')").mappings()
        }
    _upgrade(engine, "head")
    assert _snapshot(engine) == after


def test_uniqueness_is_exact_and_enforced_on_direct_inserts(legacy_catalog):
    _, engine = legacy_catalog
    _upgrade(engine, "head")
    with pytest.raises(IntegrityError), engine.begin() as connection:
        connection.execute(schema.artists.insert(), {"name": "Accept"})
    with engine.begin() as connection:
        connection.execute(schema.artists.insert(), [{"name": "ACCEPT"}, {"name": "Accept "}])
    with engine.connect() as connection:
        assert connection.execute(
            select(schema.artists.c.name).where(schema.artists.c.name.in_(("ACCEPT", "Accept ")))
        ).all() == [("ACCEPT",), ("Accept ",)]


@pytest.mark.parametrize(
    "fail_on", ["UPDATE album_artists", "CREATE UNIQUE INDEX", "UPDATE alembic_version"]
)
def test_failure_rolls_back_consolidation_index_and_revision(legacy_catalog, fail_on):
    _, engine = legacy_catalog
    before = _snapshot(engine)

    def interrupt(connection, cursor, statement, parameters, context, executemany):
        if statement.startswith(fail_on):
            assert connection.exec_driver_sql(
                "SELECT artist_id FROM track_artists WHERE track_id = 20 AND role = 'artist' "
                "ORDER BY position"
            ).all() == [(1,), (1,)]
            raise RuntimeError("simulated failure after credit consolidation")

    event.listen(engine, "before_cursor_execute", interrupt)
    try:
        with pytest.raises(RuntimeError, match="simulated failure"):
            _upgrade(engine, "head")
    finally:
        event.remove(engine, "before_cursor_execute", interrupt)
    assert _snapshot(engine) == before
    with engine.connect() as connection:
        assert validate_catalog_connection(connection) == schema.LEGACY_REVISION
        assert not {"uq_artists_name", "ix_artists_name_consolidation"} & {
            row["name"]
            for row in connection.exec_driver_sql("PRAGMA index_list('artists')").mappings()
        }


def test_downgrade_removes_only_the_index_and_does_not_recreate_duplicates(legacy_catalog):
    _, engine = legacy_catalog
    _upgrade(engine, "head")
    merged = _snapshot(engine)
    with engine.begin() as connection:
        config = db.migration_config()
        config.attributes["connection"] = connection
        command.downgrade(config, schema.LEGACY_REVISION)
    assert _snapshot(engine) == merged
    with engine.begin() as connection:
        assert validate_catalog_connection(connection) == schema.LEGACY_REVISION
        connection.execute(initial_schema.artists.insert(), {"name": "Abbath"})


@pytest.mark.parametrize(
    "replacement",
    [
        None,
        "CREATE INDEX uq_artists_name ON artists (name)",
        "CREATE UNIQUE INDEX uq_artists_name ON artists (external_id)",
        "CREATE UNIQUE INDEX uq_artists_name ON artists (name COLLATE NOCASE)",
        "CREATE UNIQUE INDEX uq_artists_name ON artists (name) WHERE external_id IS NOT NULL",
        "CREATE UNIQUE INDEX uq_artists_name ON artists (name, id)",
        "CREATE UNIQUE INDEX uq_artists_name ON artists (lower(name))",
    ],
)
def test_current_revision_rejects_missing_or_weakened_artist_index(tmp_path, replacement):
    engine = db.create_engine(tmp_path / "invalid-index.tfo")
    try:
        _upgrade(engine, "head")
        with engine.begin() as connection:
            connection.exec_driver_sql("DROP INDEX uq_artists_name")
            if replacement:
                connection.exec_driver_sql(replacement)
        with engine.connect() as connection, pytest.raises(UnknownDatabaseError):
            validate_catalog_connection(connection)
    finally:
        engine.dispose()


def test_future_revision_is_rejected(legacy_catalog):
    _, engine = legacy_catalog
    with engine.begin() as connection:
        connection.exec_driver_sql("UPDATE alembic_version SET version_num = '999_future'")
    with engine.connect() as connection, pytest.raises(UnknownDatabaseError, match="revisión"):
        validate_catalog_connection(connection)


def test_offline_upgrade_is_reproducible_and_matches_populated_online_upgrade(
    legacy_catalog, tmp_path
):
    path, engine = legacy_catalog
    offline_path = tmp_path / "offline-upgraded.tfo"
    with sqlite3.connect(path) as original, sqlite3.connect(offline_path) as offline:
        original.backup(offline)
    output = io.StringIO()
    command.upgrade(
        db.migration_config(output), f"{schema.LEGACY_REVISION}:{schema.REVISION}", sql=True
    )
    repeated = io.StringIO()
    command.upgrade(
        db.migration_config(repeated), f"{schema.LEGACY_REVISION}:{schema.REVISION}", sql=True
    )
    assert output.getvalue() == repeated.getvalue()
    with sqlite3.connect(offline_path) as offline:
        offline.executescript(output.getvalue())
    _upgrade(engine, "head")
    offline_engine = db.create_engine(offline_path)
    try:
        assert _snapshot(offline_engine) == _snapshot(engine)
        with offline_engine.connect() as connection:
            assert validate_catalog_connection(connection, require_current=True) == schema.REVISION
    finally:
        offline_engine.dispose()
