"""Application/repository integration with temporary SQLite and invented metadata."""

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from threading import Barrier

import pytest
from alembic import command
from sqlalchemy import event, func, select
from sqlalchemy.exc import IntegrityError, OperationalError

from trackfolio.application.catalog import GetTrack, ImportAudio, ListTracks, ListTrackSummaries
from trackfolio.domain.catalog import CatalogSummary
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
    # Track and album credits share an artist identity.
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


def test_albums_keep_their_context_and_share_artists_with_raw_values_preserved(
    repository, tmp_path
):
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
    assert count(repository, db.albums) == 2
    assert count(repository, db.artists) == 1
    assert count(repository, db.genres) == 1
    assert count(repository, db.audio_files) == 3
    assert count(repository, db.raw_tags) == 6


def test_artist_identity_is_shared_across_albums_folders_libraries_and_no_album(
    repository, tmp_path
):
    metadata = TrackMetadata(
        artists=("Accept",), album="Album A", album_artists=("Accept",), audio_format="flac"
    )
    first_library = tmp_path / "Library A"
    second_library = tmp_path / "Library B"
    imports = (
        (first_library, "Edition A/first.flac", metadata),
        (first_library, "Edition A/second.flac", metadata),
        (first_library, "Edition B/first.flac", replace(metadata, album="Album B")),
        (second_library, "Edition A/first.flac", metadata),
        (second_library, "Loose/first.flac", replace(metadata, album=None, album_artists=())),
        (first_library, "Other/second.flac", replace(metadata, album=None, album_artists=())),
    )
    entries = [repository.save(tags, root, path) for root, path, tags in imports]
    assert count(repository, db.artists) == 1
    assert count(repository, db.albums) == 3
    assert count(repository, db.libraries) == 2
    assert count(repository, db.tracks) == count(repository, db.audio_files) == len(imports)
    with repository.engine.connect() as connection:
        artist_id = connection.execute(select(db.artists.c.id)).scalar_one()
        for credits in (db.track_artists, db.album_artists):
            assert set(connection.execute(select(credits.c.artist_id)).scalars()) == {artist_id}
    repeated = repository.save(metadata, first_library, "Edition A/first.flac")
    assert repeated == entries[0]
    assert count(repository, db.artists) == 1


def test_exact_names_and_multiple_credits_keep_their_text_roles_and_order(repository, tmp_path):
    metadata = TrackMetadata(
        artists=("Accept", "ACCEPT", " Accept", "Accept", "", "  "),
        album_artists=(" Accept", "Accept", "ACCEPT", "Accept"),
        audio_format="flac",
    )
    entry = repository.save(metadata, tmp_path, "track.flac")
    assert entry.metadata.artists == ("Accept", "ACCEPT", " Accept")
    assert entry.metadata.album_artists == (" Accept", "Accept", "ACCEPT")
    assert count(repository, db.artists) == 3
    with repository.engine.connect() as connection:
        artist_ids = dict(connection.execute(select(db.artists.c.name, db.artists.c.id)).all())
        track_credits = connection.execute(
            select(
                db.track_artists.c.artist_id, db.track_artists.c.role, db.track_artists.c.position
            )
            .where(db.track_artists.c.track_id == entry.track_id)
            .order_by(db.track_artists.c.position)
        ).all()
        album_credits = connection.execute(
            select(
                db.album_artists.c.artist_id, db.album_artists.c.role, db.album_artists.c.position
            ).order_by(db.album_artists.c.position)
        ).all()
    assert track_credits == [
        (artist_ids["Accept"], "artist", 0),
        (artist_ids["ACCEPT"], "artist", 1),
        (artist_ids[" Accept"], "artist", 2),
    ]
    assert album_credits == [
        (artist_ids[" Accept"], "album_artist", 0),
        (artist_ids["Accept"], "album_artist", 1),
        (artist_ids["ACCEPT"], "album_artist", 2),
    ]


def test_correcting_one_song_reuses_accept_and_keeps_other_abbath_credits(repository, tmp_path):
    original = TrackMetadata(
        title="First song",
        album="Abbath album",
        artists=("Abbath",),
        album_artists=("Abbath",),
        raw_tags=(RawTagValue("ARTIST", "Abbath", 0),),
        audio_format="flac",
    )
    first = repository.save(original, tmp_path, "Abbath/first.flac")
    second = repository.save(replace(original, title="Second song"), tmp_path, "Abbath/second.flac")
    accept = repository.save(
        replace(
            original,
            title="Accept song",
            album="Accept album",
            artists=("Accept",),
            album_artists=("Accept",),
            raw_tags=(RawTagValue("ARTIST", "Accept", 0),),
        ),
        tmp_path,
        "Accept/accept.flac",
    )
    with repository.engine.connect() as connection:
        artists_before = connection.execute(select(db.artists).order_by(db.artists.c.id)).all()
        albums_before = connection.execute(select(db.albums).order_by(db.albums.c.id)).all()
        album_credits_before = connection.execute(
            select(db.album_artists).order_by(db.album_artists.c.album_id)
        ).all()
        artist_ids = dict(connection.execute(select(db.artists.c.name, db.artists.c.id)).all())
    corrected_metadata = replace(
        original, artists=("Accept",), raw_tags=(RawTagValue("ARTIST", "Accept", 0),)
    )
    corrected = repository.save(corrected_metadata, tmp_path, "Abbath/first.flac")
    assert (corrected.file_id, corrected.track_id) == (first.file_id, first.track_id)
    assert corrected.metadata == corrected_metadata
    assert repository.get(second.file_id) == second
    assert repository.get(accept.file_id) == accept
    assert repository.save(corrected_metadata, tmp_path, "Abbath/first.flac") == corrected
    with repository.engine.connect() as connection:
        assert (
            connection.execute(select(db.artists).order_by(db.artists.c.id)).all() == artists_before
        )
        assert connection.execute(select(db.albums).order_by(db.albums.c.id)).all() == albums_before
        assert (
            connection.execute(select(db.album_artists).order_by(db.album_artists.c.album_id)).all()
            == album_credits_before
        )
        assert (
            connection.execute(
                select(db.track_artists.c.artist_id).where(
                    db.track_artists.c.track_id == first.track_id
                )
            ).scalar_one()
            == artist_ids["Accept"]
        )
        assert (
            connection.execute(
                select(db.track_artists.c.artist_id).where(
                    db.track_artists.c.track_id == second.track_id
                )
            ).scalar_one()
            == artist_ids["Abbath"]
        )


def test_repository_rejects_writes_to_initial_schema_without_migrating_it(tmp_path):
    path = tmp_path / "initial.tfo"
    with sqlite3.connect(path) as connection:
        connection.executescript(db.initial_schema_sql())
    before = path.read_bytes()
    engine = db.create_engine(path)
    try:
        with pytest.raises(db.UnknownDatabaseError):
            SqliteCatalogRepository(engine).save(
                TrackMetadata(artists=("Accept",), audio_format="flac"), tmp_path, "track.flac"
            )
    finally:
        engine.dispose()
    assert path.read_bytes() == before


@pytest.mark.parametrize(
    "change", ["drop_index", "downgrade", "revision_without_ddl", "application_id_without_ddl"]
)
def test_cached_write_validation_rejects_changes_to_schema_revision_or_identity(
    repository, tmp_path, change
):
    metadata = TrackMetadata(artists=("Accept",), audio_format="flac")
    entry = repository.save(metadata, tmp_path, "first.flac")
    with repository.engine.begin() as connection:
        if change == "drop_index":
            connection.exec_driver_sql("DROP INDEX uq_artists_name")
        elif change == "downgrade":
            config = db.migration_config()
            config.attributes["connection"] = connection
            command.downgrade(config, "001_initial")
        elif change == "revision_without_ddl":
            connection.exec_driver_sql("UPDATE alembic_version SET version_num = '001_initial'")
        else:
            schema_version = connection.exec_driver_sql("PRAGMA schema_version").scalar_one()
            connection.exec_driver_sql("PRAGMA application_id = 0")
            assert (
                connection.exec_driver_sql("PRAGMA schema_version").scalar_one() == schema_version
            )
    with pytest.raises(db.UnknownDatabaseError):
        repository.save(metadata, tmp_path, "second.flac")
    assert repository.get(entry.file_id) == entry
    assert count(repository, db.audio_files) == count(repository, db.artists) == 1


def test_two_writers_share_a_new_artist_and_keep_successful_imports(repository, tmp_path):
    # SQLite may reject one concurrent deferred transaction; retry after its peer commits.
    barrier = Barrier(2)
    database = repository.engine.url.database
    assert database is not None
    second_engine = db.create_engine(database)
    second_repository = SqliteCatalogRepository(second_engine)
    metadata = TrackMetadata(artists=("Accept",), album="Shared album", audio_format="flac")
    writers = (repository, second_repository)

    def save_together(index):
        barrier.wait(timeout=5)
        try:
            return writers[index].save(metadata, tmp_path, f"song{index}.flac")
        except OperationalError as error:
            if getattr(error.orig, "sqlite_errorcode", 0) & 0xFF != sqlite3.SQLITE_BUSY:
                raise
            return None

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(save_together, range(2)))
        for index, result in enumerate(results):
            if result is None:
                results[index] = writers[index].save(metadata, tmp_path, f"song{index}.flac")
        assert all(result is not None for result in results)
        assert count(repository, db.artists) == count(repository, db.albums) == 1
        assert count(repository, db.audio_files) == count(repository, db.tracks) == 2
        with repository.engine.connect() as connection:
            artist_id = connection.execute(select(db.artists.c.id)).scalar_one()
            assert list(connection.execute(select(db.track_artists.c.artist_id)).scalars()) == [
                artist_id,
                artist_id,
            ]
    finally:
        second_engine.dispose()


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


def test_summary_query_has_no_details_per_row_and_preserves_credits(
    repository, tmp_path, monkeypatch
):
    first = repository.save(
        TrackMetadata(
            title="Song",
            artists=("Second alphabetically", "First alphabetically"),
            album="Album",
            album_year=2021,
            lyrics="Heavy field excluded from the list",
            artwork=Artwork(b"excluded from the list", "image/png"),
            raw_tags=(RawTagValue("CUSTOM", "excluded from the list", 0),),
            audio_format="flac",
        ),
        tmp_path,
        "Album/song.flac",
    )
    second = repository.save(TrackMetadata(audio_format="mp3"), tmp_path, "empty.mp3")
    statements = []

    def capture(_connection, _cursor, statement, _parameters, _context, _executemany):
        statements.append(statement.lower())

    def no_details(_file_id):
        pytest.fail("Listing summaries must not retrieve each file's detail")

    monkeypatch.setattr(repository, "get", no_details)
    event.listen(repository.engine, "before_cursor_execute", capture)
    try:
        summaries = ListTrackSummaries(repository).execute()
    finally:
        event.remove(repository.engine, "before_cursor_execute", capture)
    assert summaries == (
        CatalogSummary(
            first.file_id,
            first.track_id,
            "Song",
            ("Second alphabetically", "First alphabetically"),
            "Album",
            2021,
            "Album/song.flac",
        ),
        CatalogSummary(second.file_id, second.track_id, None, (), None, None, "empty.mp3"),
    )
    assert len(statements) == 1
    for excluded in ("lyrics", "artworks", "raw_tags", "track_details"):
        assert excluded not in statements[0]


def test_summary_listing_returns_no_rows_for_an_empty_catalog(repository):
    assert ListTrackSummaries(repository).execute() == ()
