"""Editing contracts and persistence against real temporary SQLite catalogues."""

import sqlite3
from contextlib import closing
from dataclasses import replace

import pytest
from sqlalchemy import delete, insert, select, update

from trackfolio.application.catalog import CatalogAccessError, GetTrack
from trackfolio.application.edit_catalog import (
    CatalogEditConflict,
    CatalogEditError,
    CatalogEditValidationError,
    CatalogRecordMissing,
    FindArtists,
    FindGenres,
    GetEditableTrack,
    UpdateCatalogTrack,
)
from trackfolio.domain.catalog_edit import FieldChange, TrackEditPatch
from trackfolio.domain.metadata import Artwork, RawTagValue, TrackMetadata
from trackfolio.infrastructure import database as db
from trackfolio.infrastructure.catalog import SqliteCatalogRepository
from trackfolio.infrastructure.catalog_edit import SqliteCatalogEditSessionFactory


@pytest.fixture
def catalogue(tmp_path):
    path = tmp_path / "catálogo editable %.tfo"
    db.migrate_database(path)
    engine = db.create_engine(path)
    try:
        yield path, SqliteCatalogRepository(engine)
    finally:
        engine.dispose()


@pytest.fixture
def rich_metadata():
    return TrackMetadata(
        title="Original",
        album="Shared album",
        album_year=2020,
        album_date="2020-05-03",
        track_number=1,
        track_total=9,
        disc_number=1,
        disc_total=2,
        artists=("Abbath",),
        album_artists=("Abbath",),
        genres=("Metal", "Rock"),
        lyrics="Original lyrics\nSecond line\n",
        artwork=Artwork(b"synthetic artwork", "image/png", 1, 1),
        raw_tags=(RawTagValue("ARTIST", "Abbath", 0),),
        audio_format="flac",
        duration_seconds=123.5,
        sample_rate_hz=44100,
        channels=2,
        bits_per_sample=16,
    )


def patch(**values):
    return TrackEditPatch(tuple(FieldChange(field, value) for field, value in values.items()))


def editable(path, file_id):
    session = SqliteCatalogEditSessionFactory().open_reader(path)
    try:
        result = session.get_editable(file_id)
        assert result is not None
        return result
    finally:
        session.close()


def edit(path, file_id, **values):
    original = editable(path, file_id)
    outcome = UpdateCatalogTrack(SqliteCatalogEditSessionFactory()).execute(
        path, original, patch(**values)
    )
    assert outcome is not None
    return outcome


def rows(repository, table):
    with repository.engine.connect() as connection:
        return tuple(connection.execute(select(table)).all())


def all_rows(repository):
    return {
        table.name: rows(repository, table)
        for table in (
            db.libraries,
            db.albums,
            db.tracks,
            db.artists,
            db.genres,
            db.track_artists,
            db.album_artists,
            db.track_genres,
            db.artworks,
            db.audio_files,
            db.raw_tags,
        )
    }


class NeverWriterFactory:
    def open_writer(self, _path):
        raise AssertionError("Validation and effective no-op must not open a writer")


@pytest.mark.parametrize("change", [TrackEditPatch(()), patch(title="Original")])
def test_empty_or_unchanged_patch_never_opens_writer(catalogue, tmp_path, rich_metadata, change):
    path, repository = catalogue
    entry = repository.save(rich_metadata, tmp_path / "missing music", "01.flac")
    original = editable(path, entry.file_id)
    before = path.read_bytes()
    assert UpdateCatalogTrack(NeverWriterFactory()).execute(path, original, change) is None
    assert path.read_bytes() == before
    assert not list(tmp_path.glob("*.bak"))


@pytest.mark.parametrize(
    "field,value",
    [
        ("album_year", 0),
        ("album_year", 10000),
        ("album_year", "2020.5"),
        ("track_number", 0),
        ("track_number", -1),
        ("track_number", 1.5),
        ("track_number", True),
        ("track_total", "ten"),
        ("disc_number", 0),
        ("disc_total", -1),
        ("artists", "Accept"),
        ("genres", ("Rock", 2)),
        ("title", 7),
        ("lyrics", 7),
    ],
)
def test_invalid_values_identify_field_before_opening_writer(
    catalogue, tmp_path, rich_metadata, field, value
):
    path, repository = catalogue
    entry = repository.save(rich_metadata, tmp_path, "01.flac")
    original = editable(path, entry.file_id)
    with pytest.raises(CatalogEditValidationError) as captured:
        UpdateCatalogTrack(NeverWriterFactory()).execute(path, original, patch(**{field: value}))
    assert field in {error.field for error in captured.value.errors}


@pytest.mark.parametrize("values", [{"track_number": 10}, {"track_total": 0}, {"disc_number": 3}])
def test_changed_number_pair_is_checked(catalogue, tmp_path, rich_metadata, values):
    path, repository = catalogue
    entry = repository.save(rich_metadata, tmp_path, "01.flac")
    with pytest.raises(CatalogEditValidationError):
        UpdateCatalogTrack(NeverWriterFactory()).execute(
            path, editable(path, entry.file_id), patch(**values)
        )


def test_old_inconsistent_numbers_do_not_block_unrelated_edit(catalogue, tmp_path, rich_metadata):
    path, repository = catalogue
    entry = repository.save(replace(rich_metadata, track_number=10), tmp_path, "01.flac")
    edit(path, entry.file_id, title="Corrected")
    updated = GetTrack(repository).execute(entry.file_id)
    assert updated.metadata.title == "Corrected"
    assert updated.metadata.track_number == 10
    assert updated.metadata.track_total == 9


@pytest.mark.parametrize(
    "values", [{"track_number": None}, {"track_total": None}, {"disc_total": None}]
)
def test_numbers_can_be_cleared_independently(catalogue, tmp_path, rich_metadata, values):
    path, repository = catalogue
    entry = repository.save(rich_metadata, tmp_path, "01.flac")
    edit(path, entry.file_id, **values)
    updated = GetTrack(repository).execute(entry.file_id)
    for field in values:
        assert getattr(updated.metadata, field) is None


def test_numeric_text_is_normalized_and_omitted_fields_stay_intact(
    catalogue, tmp_path, rich_metadata
):
    path, repository = catalogue
    entry = repository.save(rich_metadata, tmp_path, "01.flac")
    outcome = edit(path, entry.file_id, album_year=" 2021 ", track_number="", track_total="12")
    expected = replace(rich_metadata, album_year=2021, track_number=None, track_total=12)
    assert GetTrack(repository).execute(entry.file_id).metadata == expected
    assert outcome.entry.metadata == expected
    assert outcome.summary.album_year == 2021
    assert outcome.backup_path is None


def test_reader_lookups_escape_wildcards_and_resolve_exact_artist_ids(
    catalogue, tmp_path, rich_metadata
):
    path, repository = catalogue
    entry = repository.save(
        replace(
            rich_metadata,
            artists=("Accept", "ACCEPT", "100% artist", "under_score"),
            genres=("100% genre", "under_score", "Metal"),
        ),
        tmp_path,
        "01.flac",
    )
    before = path.read_bytes()
    session = SqliteCatalogEditSessionFactory().open_reader(path)
    try:
        assert GetEditableTrack(session).execute(9999) is None
        original = GetEditableTrack(session).execute(entry.file_id)
        choices = FindArtists(session).execute("accept")
        assert {choice.name for choice in choices} == {"Accept", "ACCEPT"}
        with repository.engine.connect() as connection:
            for choice in choices:
                assert (
                    connection.execute(
                        select(db.artists.c.name).where(db.artists.c.id == choice.artist_id)
                    ).scalar_one()
                    == choice.name
                )
        assert tuple(choice.name for choice in FindArtists(session).execute("%")) == (
            "100% artist",
        )
        assert tuple(choice.name for choice in FindArtists(session).execute("_")) == (
            "under_score",
        )
        assert FindGenres(session).execute("%") == ("100% genre",)
        assert FindGenres(session).execute("_") == ("under_score",)
        assert FindGenres(session).execute("missing") == ()
        with pytest.raises(CatalogEditError):
            session.apply_edit(original, patch(title="Reader cannot write"))
    finally:
        session.close()
    assert path.read_bytes() == before


def test_closed_edit_session_rejects_reuse(catalogue, tmp_path, rich_metadata):
    path, repository = catalogue
    entry = repository.save(rich_metadata, tmp_path, "01.flac")
    session = SqliteCatalogEditSessionFactory().open_reader(path)
    session.close()
    session.close()
    with pytest.raises(CatalogEditError):
        session.get_editable(entry.file_id)
    with pytest.raises(CatalogEditError):
        session.find_artists("")


def test_duplicate_patch_fields_are_rejected_before_writer(catalogue, tmp_path, rich_metadata):
    path, repository = catalogue
    entry = repository.save(rich_metadata, tmp_path, "01.flac")
    change = TrackEditPatch((FieldChange("title", "First"), FieldChange("title", "Second")))
    with pytest.raises(CatalogEditValidationError) as captured:
        UpdateCatalogTrack(NeverWriterFactory()).execute(
            path, editable(path, entry.file_id), change
        )
    assert {error.field for error in captured.value.errors} == {"title"}


def test_blank_scalars_and_exact_ordered_names_preserve_literal_lyrics(
    catalogue, tmp_path, rich_metadata
):
    path, repository = catalogue
    entry = repository.save(rich_metadata, tmp_path, "01.flac")
    edit(
        path,
        entry.file_id,
        title=" \t",
        artists=("Accept", "ACCEPT", "Accept", "  Accept  ", " ", "Artist, Jr.; Ensemble"),
        genres=("Rock", "Rock", "ROCK", " ", "Genre, literal"),
        lyrics="  <b>Literal text</b>\n\n",
    )
    updated = GetTrack(repository).execute(entry.file_id)
    assert updated.metadata.title is None
    assert updated.metadata.artists == ("Accept", "ACCEPT", "  Accept  ", "Artist, Jr.; Ensemble")
    assert updated.metadata.genres == ("Rock", "ROCK", "Genre, literal")
    assert updated.metadata.lyrics == "  <b>Literal text</b>\n\n"


def test_reassign_artist_reuses_id_and_preserves_other_tracks_and_all_hidden_data(
    catalogue, tmp_path, rich_metadata
):
    path, repository = catalogue
    first = repository.save(rich_metadata, tmp_path / "missing music", "album/01.flac")
    sibling = repository.save(
        replace(rich_metadata, title="Sibling"), first.library_root, "album/02.flac"
    )
    existing = repository.save(
        replace(rich_metadata, title="Accept song", artists=("Accept",)),
        first.library_root,
        "elsewhere/accept.flac",
    )
    with repository.engine.begin() as connection:
        accept_id = connection.execute(
            select(db.artists.c.id).where(db.artists.c.name == "Accept")
        ).scalar_one()
        connection.execute(
            insert(db.track_artists).values(
                track_id=first.track_id, role="composer", position=0, artist_id=accept_id
            )
        )
        connection.execute(
            insert(db.album_artists).values(
                album_id=connection.execute(
                    select(db.tracks.c.album_id).where(db.tracks.c.id == first.track_id)
                ).scalar_one(),
                role="producer",
                position=0,
                artist_id=accept_id,
            )
        )
    before = all_rows(repository)
    sibling_before = GetTrack(repository).execute(sibling.file_id)
    edit(path, first.file_id, artists=("Accept",))
    after = all_rows(repository)
    assert after["artists"] == before["artists"]
    for table in ("albums", "album_artists", "artworks", "audio_files", "raw_tags", "track_genres"):
        assert after[table] == before[table]
    assert GetTrack(repository).execute(sibling.file_id) == sibling_before
    assert GetTrack(repository).execute(existing.file_id) == existing
    with repository.engine.connect() as connection:
        credits = connection.execute(
            select(
                db.track_artists.c.role, db.track_artists.c.artist_id, db.track_artists.c.position
            )
            .where(db.track_artists.c.track_id == first.track_id)
            .order_by(db.track_artists.c.role)
        ).all()
        view = connection.exec_driver_sql(
            "SELECT artists FROM track_details WHERE file_id=?", (first.file_id,)
        ).scalar_one()
    assert credits == [("artist", accept_id, 0), ("composer", accept_id, 0)]
    assert GetTrack(repository).execute(first.file_id).metadata.artists == ("Accept",)
    assert "Accept" in view
    assert next(
        item for item in repository.list_summaries() if item.file_id == first.file_id
    ).artists == ("Accept",)


def test_only_selected_artist_and_genre_relations_are_cleared(catalogue, tmp_path, rich_metadata):
    path, repository = catalogue
    entry = repository.save(rich_metadata, tmp_path, "01.flac")
    before = all_rows(repository)
    edit(path, entry.file_id, artists=(), genres=(), lyrics=None)
    updated = GetTrack(repository).execute(entry.file_id)
    assert updated.metadata.artists == ()
    assert updated.metadata.genres == ()
    assert updated.metadata.lyrics is None
    assert rows(repository, db.artists) == before["artists"]
    assert rows(repository, db.genres) == before["genres"]
    assert rows(repository, db.album_artists) == before["album_artists"]
    assert updated.metadata.raw_tags == rich_metadata.raw_tags


def test_album_edit_reassigns_one_track_preserving_date_disc_total_and_hidden_credits(
    catalogue, tmp_path, rich_metadata
):
    path, repository = catalogue
    first = repository.save(rich_metadata, tmp_path, "album/01.flac")
    sibling = repository.save(replace(rich_metadata, title="Sibling"), tmp_path, "album/02.flac")
    with repository.engine.begin() as connection:
        old_album = connection.execute(
            select(db.tracks.c.album_id).where(db.tracks.c.id == first.track_id)
        ).scalar_one()
        artist_id = connection.execute(select(db.artists.c.id)).scalar_one()
        connection.execute(
            insert(db.album_artists).values(
                album_id=old_album, role="producer", position=0, artist_id=artist_id
            )
        )
    old_album_rows = rows(repository, db.albums)
    edit(path, first.file_id, album="Corrected album", album_year=2022, disc_total=3)
    updated = GetTrack(repository).execute(first.file_id)
    assert updated.metadata.album == "Corrected album"
    assert updated.metadata.album_year == 2022
    assert updated.metadata.album_date == rich_metadata.album_date
    assert updated.metadata.disc_total == 3
    assert GetTrack(repository).execute(sibling.file_id).metadata.album == "Shared album"
    with repository.engine.connect() as connection:
        new_album = connection.execute(
            select(db.tracks.c.album_id).where(db.tracks.c.id == first.track_id)
        ).scalar_one()
        assert new_album != old_album
        assert (
            connection.execute(select(db.albums).where(db.albums.c.id == old_album)).one()
            == old_album_rows[0]
        )
        assert (
            connection.execute(
                select(db.albums.c.disc_total).where(db.albums.c.id == new_album)
            ).scalar_one()
            == 2
        )
        roles = (
            connection.execute(
                select(db.album_artists.c.role).where(db.album_artists.c.album_id == new_album)
            )
            .scalars()
            .all()
        )
    assert sorted(roles) == ["album_artist", "producer"]


@pytest.mark.parametrize("additional_role", [None, "producer"])
def test_compatible_existing_album_is_reused(catalogue, tmp_path, rich_metadata, additional_role):
    path, repository = catalogue
    first = repository.save(rich_metadata, tmp_path, "album/01.flac")
    target = repository.save(replace(rich_metadata, album="Target"), tmp_path, "album/02.flac")
    if additional_role is not None:
        with repository.engine.begin() as connection:
            artist_id = connection.execute(select(db.artists.c.id)).scalar_one()
            for track_id in (first.track_id, target.track_id):
                album_id = connection.execute(
                    select(db.tracks.c.album_id).where(db.tracks.c.id == track_id)
                ).scalar_one()
                connection.execute(
                    insert(db.album_artists).values(
                        album_id=album_id,
                        role=additional_role,
                        position=0,
                        artist_id=artist_id,
                    )
                )
    before_albums = rows(repository, db.albums)
    before_credits = rows(repository, db.album_artists)
    edit(path, first.file_id, album="Target")
    with repository.engine.connect() as connection:
        assert (
            connection.execute(
                select(db.tracks.c.album_id).where(db.tracks.c.id == first.track_id)
            ).scalar_one()
            == connection.execute(
                select(db.tracks.c.album_id).where(db.tracks.c.id == target.track_id)
            ).scalar_one()
        )
    assert rows(repository, db.albums) == before_albums
    assert rows(repository, db.album_artists) == before_credits


def test_incompatible_album_roles_conflict_without_partial_changes(
    catalogue, tmp_path, rich_metadata
):
    path, repository = catalogue
    first = repository.save(rich_metadata, tmp_path, "album/01.flac")
    repository.save(replace(rich_metadata, album="Target"), tmp_path, "album/02.flac")
    with repository.engine.begin() as connection:
        old_album = connection.execute(
            select(db.tracks.c.album_id).where(db.tracks.c.id == first.track_id)
        ).scalar_one()
        artist_id = connection.execute(select(db.artists.c.id)).scalar_one()
        connection.execute(
            insert(db.album_artists).values(
                album_id=old_album, role="producer", position=0, artist_id=artist_id
            )
        )
    before = all_rows(repository)
    with pytest.raises(CatalogEditConflict):
        edit(path, first.file_id, album="Target", artists=("New artist",), title="New title")
    assert all_rows(repository) == before


def test_clearing_album_title_preserves_remaining_album_data(catalogue, tmp_path, rich_metadata):
    path, repository = catalogue
    entry = repository.save(rich_metadata, tmp_path, "album/01.flac")
    edit(path, entry.file_id, album=" \t", album_year=None)
    updated = GetTrack(repository).execute(entry.file_id)
    assert updated.metadata.album is None
    assert updated.metadata.album_year is None
    assert updated.metadata.album_date == rich_metadata.album_date
    assert updated.metadata.album_artists == rich_metadata.album_artists
    with repository.engine.connect() as connection:
        assert connection.execute(select(db.tracks.c.album_id)).scalar_one() is not None


def test_clearing_last_album_value_removes_selected_relation(catalogue, tmp_path):
    path, repository = catalogue
    entry = repository.save(
        TrackMetadata(album="Only data", audio_format="flac"), tmp_path, "01.flac"
    )
    edit(path, entry.file_id, album=None)
    with repository.engine.connect() as connection:
        assert connection.execute(select(db.tracks.c.album_id)).scalar_one() is None


def share_track(repository, file_id, relative_path):
    with repository.engine.begin() as connection:
        source = dict(
            connection.execute(select(db.audio_files).where(db.audio_files.c.id == file_id))
            .mappings()
            .one()
        )
        source.pop("id")
        source["relative_path"] = relative_path
        sibling_id = connection.execute(
            insert(db.audio_files).values(**source)
        ).inserted_primary_key[0]
        for row in (
            connection.execute(select(db.raw_tags).where(db.raw_tags.c.file_id == file_id))
            .mappings()
            .all()
        ):
            connection.execute(insert(db.raw_tags).values(**{**row, "file_id": sibling_id}))
        return sibling_id


def test_shared_track_is_copied_before_edit_with_all_relations(catalogue, tmp_path, rich_metadata):
    path, repository = catalogue
    first = repository.save(rich_metadata, tmp_path, "album/01.flac")
    with repository.engine.begin() as connection:
        artist_id = connection.execute(select(db.artists.c.id)).scalar_one()
        connection.execute(
            insert(db.track_artists).values(
                track_id=first.track_id, role="composer", position=0, artist_id=artist_id
            )
        )
    sibling_id = share_track(repository, first.file_id, "album/01-copy.flac")
    sibling_before = GetTrack(repository).execute(sibling_id)
    edit(path, first.file_id, title="Selected correction")
    updated = GetTrack(repository).execute(first.file_id)
    assert updated.file_id == first.file_id
    assert updated.track_id != first.track_id
    assert updated.metadata == replace(first.metadata, title="Selected correction")
    assert GetTrack(repository).execute(sibling_id) == sibling_before
    with repository.engine.connect() as connection:
        old_roles = connection.execute(
            select(
                db.track_artists.c.role, db.track_artists.c.position, db.track_artists.c.artist_id
            )
            .where(db.track_artists.c.track_id == first.track_id)
            .order_by(db.track_artists.c.role)
        ).all()
        new_roles = connection.execute(
            select(
                db.track_artists.c.role, db.track_artists.c.position, db.track_artists.c.artist_id
            )
            .where(db.track_artists.c.track_id == updated.track_id)
            .order_by(db.track_artists.c.role)
        ).all()
    assert new_roles == old_roles


def test_import_update_also_detaches_shared_track(catalogue, tmp_path, rich_metadata):
    _path, repository = catalogue
    first = repository.save(rich_metadata, tmp_path, "album/01.flac")
    sibling_id = share_track(repository, first.file_id, "album/01-copy.flac")
    sibling_before = GetTrack(repository).execute(sibling_id)
    imported = repository.save(
        replace(rich_metadata, title="Reimported", artists=("Accept",)), tmp_path, "album/01.flac"
    )
    assert imported.file_id == first.file_id
    assert imported.track_id != first.track_id
    assert imported.metadata.title == "Reimported"
    assert GetTrack(repository).execute(sibling_id) == sibling_before


def test_second_editor_detects_first_save_and_keeps_first_change(
    catalogue, tmp_path, rich_metadata
):
    path, repository = catalogue
    entry = repository.save(rich_metadata, tmp_path, "01.flac")
    first = editable(path, entry.file_id)
    second = editable(path, entry.file_id)
    use_case = UpdateCatalogTrack(SqliteCatalogEditSessionFactory())
    use_case.execute(path, first, patch(title="First editor"))
    before = all_rows(repository)
    with pytest.raises(CatalogEditConflict):
        use_case.execute(path, second, patch(artists=("New artist",)))
    assert all_rows(repository) == before
    assert GetTrack(repository).execute(entry.file_id).metadata.title == "First editor"


def test_external_hidden_album_change_invalidates_token(catalogue, tmp_path, rich_metadata):
    path, repository = catalogue
    entry = repository.save(rich_metadata, tmp_path, "01.flac")
    original = editable(path, entry.file_id)
    with repository.engine.begin() as connection:
        connection.execute(update(db.albums).values(date="2020-06-04"))
    with pytest.raises(CatalogEditConflict):
        UpdateCatalogTrack(SqliteCatalogEditSessionFactory()).execute(
            path, original, patch(title="Stale correction")
        )
    assert GetTrack(repository).execute(entry.file_id).metadata.title == "Original"


def test_deleted_record_has_distinct_error(catalogue, tmp_path, rich_metadata):
    path, repository = catalogue
    entry = repository.save(rich_metadata, tmp_path, "01.flac")
    original = editable(path, entry.file_id)
    with repository.engine.begin() as connection:
        connection.execute(delete(db.audio_files).where(db.audio_files.c.id == entry.file_id))
    with pytest.raises(CatalogRecordMissing):
        UpdateCatalogTrack(SqliteCatalogEditSessionFactory()).execute(
            path, original, patch(title="Correction")
        )


def test_missing_database_is_never_recreated(catalogue, tmp_path, rich_metadata):
    path, repository = catalogue
    entry = repository.save(rich_metadata, tmp_path, "01.flac")
    original = editable(path, entry.file_id)
    repository.engine.dispose()
    path.unlink()
    with pytest.raises(CatalogAccessError):
        UpdateCatalogTrack(SqliteCatalogEditSessionFactory()).execute(
            path, original, patch(title="Correction")
        )
    assert not path.exists()


def test_writer_lock_failure_preserves_all_data(catalogue, tmp_path, rich_metadata):
    path, repository = catalogue
    entry = repository.save(rich_metadata, tmp_path, "01.flac")
    original = editable(path, entry.file_id)
    before = all_rows(repository)
    with closing(sqlite3.connect(path, autocommit=True)) as locked:
        locked.execute("BEGIN IMMEDIATE")
        try:
            with pytest.raises(CatalogAccessError):
                UpdateCatalogTrack(SqliteCatalogEditSessionFactory()).execute(
                    path, original, patch(artists=("New artist",))
                )
        finally:
            locked.execute("ROLLBACK")
    assert all_rows(repository) == before


def test_failure_in_relation_write_rolls_back_entities_and_track_changes(
    catalogue, tmp_path, rich_metadata
):
    path, repository = catalogue
    entry = repository.save(rich_metadata, tmp_path, "01.flac")
    original = editable(path, entry.file_id)
    with repository.engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TRIGGER fail_edit_genres BEFORE INSERT ON track_genres "
            "BEGIN SELECT RAISE(ABORT, 'injected relation failure'); END"
        )
    before = all_rows(repository)
    with pytest.raises(CatalogAccessError):
        UpdateCatalogTrack(SqliteCatalogEditSessionFactory()).execute(
            path, original, patch(title="Changed", artists=("New artist",), genres=("New genre",))
        )
    assert all_rows(repository) == before


def legacy_catalog(path, library):
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.executescript(db.initial_schema_sql())
        connection.execute("INSERT INTO libraries(id,root_path) VALUES(1,?)", (library.as_posix(),))
        connection.execute("INSERT INTO tracks(id,title) VALUES(1,'Original')")
        connection.execute("INSERT INTO artists(id,name) VALUES(1,'Accept'),(2,'Accept')")
        connection.execute("INSERT INTO track_artists(track_id,position,artist_id) VALUES(1,0,2)")
        connection.execute(
            "INSERT INTO audio_files(id,library_id,relative_path,track_id,format) "
            "VALUES(1,1,'01.flac',1,'FLAC')"
        )


def test_legacy_read_and_noop_leave_database_intact_then_save_backs_up_and_migrates(tmp_path):
    path = tmp_path / "legacy edit %.tfo"
    legacy_catalog(path, tmp_path / "missing music")
    before = path.read_bytes()
    original = editable(path, 1)
    assert original.values.artists == ("Accept",)
    assert path.read_bytes() == before
    use_case = UpdateCatalogTrack(SqliteCatalogEditSessionFactory())
    assert use_case.execute(path, original, TrackEditPatch(())) is None
    assert path.read_bytes() == before
    assert not list(tmp_path.glob("*.bak"))
    outcome = use_case.execute(path, original, patch(title="Legacy corrected"))
    assert outcome is not None
    backups = list(tmp_path.glob("*.bak"))
    assert len(backups) == 1
    assert outcome.backup_path == backups[0]
    with closing(sqlite3.connect(backups[0])) as saved:
        assert saved.execute("SELECT version_num FROM alembic_version").fetchone() == (
            db.LEGACY_REVISION,
        )
        assert saved.execute("SELECT title FROM tracks").fetchone() == ("Original",)
        assert saved.execute("SELECT artist_id FROM track_artists").fetchone() == (2,)
    with closing(sqlite3.connect(path)) as current:
        assert current.execute("SELECT version_num FROM alembic_version").fetchone() == (
            db.REVISION,
        )
        assert current.execute("SELECT title FROM tracks").fetchone() == ("Legacy corrected",)
        assert current.execute("SELECT artist_id FROM track_artists").fetchone() == (1,)
    edit(path, 1, title="Second correction")
    assert list(tmp_path.glob("*.bak")) == backups


def test_saved_catalogue_reopens_and_reimport_replaces_correction(
    catalogue, tmp_path, rich_metadata
):
    path, repository = catalogue
    entry = repository.save(rich_metadata, tmp_path, "01.flac")
    edit(path, entry.file_id, title="Catalogue correction", artists=("Accept",))
    reopened = editable(path, entry.file_id)
    assert reopened.values.title == "Catalogue correction"
    assert reopened.values.artists == ("Accept",)
    assert GetTrack(repository).execute(entry.file_id).metadata.raw_tags == rich_metadata.raw_tags
    imported = repository.save(rich_metadata, tmp_path, "01.flac")
    assert imported.file_id == entry.file_id
    assert imported.metadata == rich_metadata
