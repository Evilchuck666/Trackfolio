"""Application/repository integration with temporary SQLite and invented metadata."""

from dataclasses import replace

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from trackfolio.application.catalog import GetTrack, ImportAudio, ListTracks
from trackfolio.domain.metadata import Artwork, RawTagValue, TrackMetadata
from trackfolio.infrastructure import database as db
from trackfolio.infrastructure.catalog import SqliteCatalogRepository


@pytest.fixture
def repository(tmp_path):
    database = tmp_path / "catálogo con espacios.sqlite3"
    db.migrate_database(database)
    engine = db.create_engine(database)
    try:
        yield SqliteCatalogRepository(engine)
    finally:
        engine.dispose()


def count(repository, table):
    with repository.engine.connect() as connection:
        return connection.execute(select(func.count()).select_from(table)).scalar_one()


def test_import_roundtrip_uses_database_after_source_is_removed(repository, tmp_path):
    library = tmp_path / "Música"
    library.mkdir()
    source = library / "01 - título.flac"
    source.write_bytes(b"reader injected in application test")
    metadata = TrackMetadata(
        title="Título de prueba",
        album="Álbum de prueba",
        album_year=2020,
        album_date="2020-05-03",
        track_number=1,
        track_total=9,
        disc_number=2,
        disc_total=3,
        artists=("Artista B", "Artista A"),
        album_artists=("Artista A",),
        genres=("Rock", "Jazz"),
        lyrics="Texto inventado\nSegunda línea\n",
        artwork=Artwork(b"synthetic image", "image/png", 1, 1),
        raw_tags=(RawTagValue("CUSTOM", "  original  ", 0),),
        audio_format="flac",
        duration_seconds=123.5,
        sample_rate_hz=44100,
        channels=2,
        bits_per_sample=16,
    )
    entry = ImportAudio(lambda _: metadata, repository).execute(source, library)
    source.unlink()
    assert GetTrack(repository).execute(entry.file_id) == entry
    assert entry.metadata == metadata
    assert entry.library_root == library.resolve()
    assert entry.relative_path == source.name
    assert ListTracks(repository).execute() == (entry,)
    assert GetTrack(repository).execute(9999) is None
    # A shared track/album artist has a single identity in this album context.
    assert count(repository, db.artists) == 2
    with repository.engine.connect() as connection:
        row = connection.exec_driver_sql("SELECT * FROM track_details").mappings().one()
        assert row["artists"] == "Artista B; Artista A"
        assert row["album_artists"] == "Artista A"
        assert row["genres"] == "Rock; Jazz"
        assert row["lyrics"] == metadata.lyrics
        assert row["cover_bytes"] == len(metadata.artwork.data)


def test_missing_metadata_stays_null_and_is_not_inferred_from_filename(repository, tmp_path):
    source = tmp_path / "03 - This is not a metadata title.mp3"
    source.touch()
    metadata = TrackMetadata(audio_format="mp3")
    entry = ImportAudio(lambda _: metadata, repository).execute(source)
    assert entry.metadata == metadata
    assert count(repository, db.albums) == count(repository, db.artists) == 0
    assert count(repository, db.genres) == count(repository, db.artworks) == 0
    with repository.engine.connect() as connection:
        row = connection.exec_driver_sql("SELECT * FROM track_details").mappings().one()
        for field in (
            "title",
            "album",
            "album_year",
            "track_number",
            "track_total",
            "disc_number",
            "disc_total",
            "genres",
            "artists",
            "album_artists",
            "lyrics",
            "cover_source",
        ):
            assert row[field] is None, field


def test_reimport_is_idempotent_and_clears_removed_metadata(repository, tmp_path):
    source = tmp_path / "track.flac"
    source.touch()
    metadata = TrackMetadata(
        title="Original",
        album="Album",
        artists=("Artist",),
        genres=("Rock",),
        lyrics="Invented text",
        artwork=Artwork(b"image", "image/png"),
        raw_tags=(RawTagValue("TITLE", "Original", 0),),
        audio_format="flac",
    )
    importer = ImportAudio(lambda _: metadata, repository)
    first = importer.execute(source)
    second = importer.execute(source)
    assert first == second
    for table in (
        db.libraries,
        db.albums,
        db.tracks,
        db.audio_files,
        db.artists,
        db.genres,
        db.artworks,
        db.track_artists,
        db.track_genres,
        db.raw_tags,
    ):
        assert count(repository, table) == 1, table.name
    metadata = TrackMetadata(audio_format="flac")
    cleared = importer.execute(source)
    assert (cleared.file_id, cleared.track_id) == (first.file_id, first.track_id)
    assert cleared.metadata == metadata
    for table in (db.track_artists, db.track_genres, db.raw_tags):
        assert count(repository, table) == 0


def test_album_and_artist_reuse_is_contextual_and_raw_values_are_preserved(repository, tmp_path):
    metadata = TrackMetadata(
        album="Same title",
        artists=("Same name", "Same name"),
        album_artists=("Same name",),
        genres=("Rock", "Rock"),
        audio_format="flac",
        raw_tags=(RawTagValue("ARTIST", "Same name", 0), RawTagValue("ARTIST", "Same name", 1)),
    )
    a = repository.save(metadata, tmp_path, "Edition A/first.flac")
    b = repository.save(metadata, tmp_path, "Edition A/second.flac")
    c = repository.save(metadata, tmp_path, "Edition B/first.flac")
    assert a.metadata.artists == b.metadata.artists == c.metadata.artists == ("Same name",)
    assert a.metadata.raw_tags == metadata.raw_tags
    assert count(repository, db.albums) == count(repository, db.artists) == 2
    assert count(repository, db.genres) == 1
    assert count(repository, db.audio_files) == 3
    assert count(repository, db.raw_tags) == 6


def test_partial_album_metadata_without_album_title_survives(repository, tmp_path):
    metadata = TrackMetadata(album_artists=("Album credit",), audio_format="flac")
    entry = repository.save(metadata, tmp_path, "partial.flac")
    assert entry.metadata == metadata
    assert count(repository, db.albums) == 1


def test_failure_rolls_back_snapshot_and_relationship_changes(repository, tmp_path):
    metadata = TrackMetadata(title="Before", artists=("Before",), audio_format="flac")
    entry = repository.save(metadata, tmp_path, "track.flac")
    invalid = replace(metadata, title="After", album="New album", track_number=0)
    with pytest.raises(IntegrityError):
        repository.save(invalid, tmp_path, "track.flac")
    assert repository.get(entry.file_id) == entry
    assert count(repository, db.albums) == 0
    assert count(repository, db.audio_files) == count(repository, db.artists) == 1


def test_album_jpg_bytes_and_logical_location_survive_external_file_removal(repository, tmp_path):
    metadata = TrackMetadata(
        audio_format="mp3",
        artwork=Artwork(
            b"external image",
            "image/jpeg",
            2,
            2,
            "album.jpg",
            source_path=tmp_path.parent / "outside-library.jpg",
        ),
    )
    entry = repository.save(metadata, tmp_path, "Album/track.mp3")
    assert entry.metadata.artwork.data == b"external image"
    assert entry.metadata.artwork.source_path == tmp_path / "Album/album.jpg"
    with repository.engine.connect() as connection:
        row = connection.exec_driver_sql("SELECT * FROM track_details").mappings().one()
        assert row["cover_relative_path"] == "Album/album.jpg"


def test_application_rejects_file_outside_library_before_reading(repository, tmp_path):
    source = tmp_path / "outside.flac"
    source.touch()
    library = tmp_path / "library"
    library.mkdir()

    def reader(_):
        pytest.fail("Reader should not be called for a file outside the library")

    with pytest.raises(ValueError, match="dentro"):
        ImportAudio(reader, repository).execute(source, library)
    assert count(repository, db.audio_files) == count(repository, db.libraries) == 0
