"""The catalog-only instrumental mark: migration, persistence, editing and tag isolation."""

import sqlite3
from contextlib import closing

import pytest
from alembic import command
from sqlalchemy import select, update
from test_catalog_edit import catalogue as catalogue  # noqa: F401
from test_catalog_edit import edit, editable, patch, share_track
from test_tag_write import prepare_change
from test_tag_write import setup_tags as setup_tags  # noqa: F401

from trackfolio.application.edit_catalog import (
    CatalogEditValidationError,
    UpdateCatalogTracks,
    validate_edit_patch,
)
from trackfolio.application.tag_write_errors import TagWriteError
from trackfolio.application.write_tags import PreviewTagWrites
from trackfolio.domain.catalog_edit import TAG_WRITE_FIELDS, EditableValues
from trackfolio.domain.metadata import TrackMetadata
from trackfolio.domain.tag_write import TagWriteRequest
from trackfolio.infrastructure import database as db
from trackfolio.infrastructure import schema
from trackfolio.infrastructure.catalog import SqliteCatalogRepository
from trackfolio.infrastructure.catalog_edit import SqliteCatalogEditSessionFactory
from trackfolio.infrastructure.metadata import read_metadata
from trackfolio.infrastructure.schema_validation import (
    UnknownDatabaseError,
    validate_catalog_connection,
)
from trackfolio.infrastructure.session import open_catalog


@pytest.fixture
def catalog_002(tmp_path):
    """A populated catalog stored at revision 002, without the instrumental column."""
    path = tmp_path / "catalog 002.tfo"
    db.migrate_database(path)
    engine = db.create_engine(path)
    try:
        SqliteCatalogRepository(engine).save(
            TrackMetadata(title="Old song", audio_format="flac"), tmp_path, "a.flac"
        )
        with engine.begin() as connection:
            config = db.migration_config()
            config.attributes["connection"] = connection
            command.downgrade(config, schema.ARTIST_IDENTITY_REVISION)
    finally:
        engine.dispose()
    return path


def test_002_catalog_is_readable_without_migrating(catalog_002):
    before = catalog_002.read_bytes()
    session = open_catalog(catalog_002)
    try:
        (summary,) = session.list_summaries()
        entry = session.get(summary.file_id)
    finally:
        session.close()
    assert summary.title == "Old song" and summary.is_instrumental is False
    assert entry is not None and entry.instrumental is False
    assert editable(catalog_002, 1).values.instrumental is False
    assert catalog_002.read_bytes() == before


def test_upgrade_from_002_backs_up_and_adds_unmarked_column(catalog_002):
    backup = db.upgrade_database(catalog_002)
    assert backup is not None and f".{schema.ARTIST_IDENTITY_REVISION}." in backup.name
    with closing(sqlite3.connect(backup)) as saved:
        assert saved.execute("SELECT version_num FROM alembic_version").fetchone() == (
            schema.ARTIST_IDENTITY_REVISION,
        )
    with closing(sqlite3.connect(catalog_002)) as current:
        assert current.execute("SELECT version_num FROM alembic_version").fetchone() == (
            schema.REVISION,
        )
        assert current.execute("SELECT title, instrumental FROM tracks").fetchall() == [
            ("Old song", 0)
        ]
        with pytest.raises(sqlite3.IntegrityError):
            current.execute("UPDATE tracks SET instrumental = 2")


def test_downgrade_to_002_removes_the_column(catalog_002):
    db.upgrade_database(catalog_002)
    engine = db.writable_engine(catalog_002)
    try:
        with engine.begin() as connection:
            config = db.migration_config()
            config.attributes["connection"] = connection
            command.downgrade(config, schema.ARTIST_IDENTITY_REVISION)
        with engine.connect() as connection:
            assert validate_catalog_connection(connection) == schema.ARTIST_IDENTITY_REVISION
    finally:
        engine.dispose()


def test_current_revision_without_the_column_is_rejected(catalog_002):
    with closing(sqlite3.connect(catalog_002)) as connection, connection:
        connection.execute(f"UPDATE alembic_version SET version_num = '{schema.REVISION}'")
    engine = db.create_engine(catalog_002)
    try:
        with engine.connect() as connection, pytest.raises(UnknownDatabaseError):
            validate_catalog_connection(connection)
    finally:
        engine.dispose()


def test_edit_marks_song_and_reimport_and_shared_copy_keep_it(catalogue, tmp_path):  # noqa: F811
    path, repository = catalogue
    item = repository.save(TrackMetadata(title="Song", audio_format="flac"), tmp_path, "a.flac")
    edit(path, item.file_id, instrumental=True)
    (summary,) = repository.list_summaries()
    assert summary.is_instrumental is True
    assert repository.get(item.file_id).instrumental is True
    assert editable(path, item.file_id).values.instrumental is True
    repository.save(TrackMetadata(title="Renamed", audio_format="flac"), tmp_path, "a.flac")
    assert repository.get(item.file_id).instrumental is True
    sibling = share_track(repository, item.file_id, "copy.flac")
    edit(path, sibling, title="Copy")
    assert repository.get(sibling).instrumental is True
    assert repository.get(item.file_id).instrumental is True
    edit(path, item.file_id, instrumental=False)
    assert repository.get(item.file_id).instrumental is False
    assert repository.get(sibling).instrumental is True


def test_batch_edit_marks_every_selected_song(catalogue, tmp_path):  # noqa: F811
    path, repository = catalogue
    ids = [
        repository.save(TrackMetadata(title=name, audio_format="flac"), tmp_path, name).file_id
        for name in ("a.flac", "b.flac", "c.flac")
    ]
    originals = tuple(editable(path, file_id) for file_id in ids[:2])
    UpdateCatalogTracks(SqliteCatalogEditSessionFactory()).execute(
        path, originals, patch(instrumental=True)
    )
    assert [repository.get(file_id).instrumental for file_id in ids] == [True, True, False]


@pytest.mark.parametrize("value", [1, "yes", None])
def test_non_boolean_values_are_rejected(value):
    with pytest.raises(CatalogEditValidationError) as info:
        validate_edit_patch(EditableValues(), patch(instrumental=value))
    assert info.value.errors[0].field == "instrumental"


def test_external_change_to_the_mark_invalidates_the_draft(catalogue, tmp_path):  # noqa: F811
    path, repository = catalogue
    item = repository.save(TrackMetadata(title="Song", audio_format="flac"), tmp_path, "a.flac")
    original = editable(path, item.file_id)
    with repository.engine.begin() as connection:
        connection.execute(update(db.tracks).values(instrumental=True))
    assert editable(path, item.file_id).token != original.token


def test_mark_is_never_part_of_tag_writes(setup_tags, tmp_path):  # noqa: F811
    assert "instrumental" not in TAG_WRITE_FIELDS
    source, entry, preview = prepare_change(
        setup_tags, tmp_path, fields=TAG_WRITE_FIELDS, instrumental=True
    )
    before = source.read_bytes()
    assert preview.items[0].state == "unchanged"
    assert not preview.items[0].tags.differences
    assert source.read_bytes() == before
    assert EditableValues.from_metadata(read_metadata(source)).instrumental is False
    database, _repository, catalog, codec, files = setup_tags
    with pytest.raises(TagWriteError):
        PreviewTagWrites(catalog, codec, files).execute(
            TagWriteRequest(database, (entry.file_id,), ("instrumental",))
        )
    engine = db.create_engine(database)
    try:
        with engine.connect() as connection:
            assert connection.execute(select(db.tracks.c.instrumental)).scalar_one() is True
    finally:
        engine.dispose()
