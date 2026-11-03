"""Edition grouping and common edits against real SQLite, without music files."""

from dataclasses import replace

import pytest
from test_catalog_edit import catalogue as catalogue
from test_catalog_edit import edit, editable, patch
from test_catalog_edit import rich_metadata as rich_metadata

from trackfolio.application.albums import ListAlbums
from trackfolio.application.edit_catalog import CatalogEditConflict, UpdateCatalogTracks
from trackfolio.infrastructure.catalog_edit import SqliteCatalogEditSessionFactory
from trackfolio.infrastructure.session import open_catalog


def albums(path):
    session = open_catalog(path)
    try:
        return ListAlbums(session).execute()
    finally:
        session.close()


def test_multidisc_compilation_is_grouped_and_tracks_are_sorted(catalogue, rich_metadata, tmp_path):
    path, repository = catalogue
    for disc, number, artist in (
        (2, 2, "Second"),
        (1, 2, "Other"),
        (2, 1, "Third"),
        (1, 1, "First"),
    ):
        repository.save(
            replace(rich_metadata, disc_number=disc, track_number=number, artists=(artist,)),
            tmp_path,
            f"Album/CD {disc}/{number}.flac",
        )
    result = albums(path)
    assert len(result) == 1
    album = result[0]
    assert album.directory == "Album" and album.artists == ("Abbath",)
    assert [(track.disc_number, track.track_number) for track in album.tracks] == [
        (1, 1),
        (1, 2),
        (2, 1),
        (2, 2),
    ]
    assert len({track.summary.artists for track in album.tracks}) == 4
    assert album.genres == ("Metal", "Rock")


@pytest.mark.parametrize(
    "difference", ["folder", "library", "year", "artists", "date", "unnumbered-disc", "wrong-disc"]
)
def test_different_editions_are_not_merged(catalogue, rich_metadata, tmp_path, difference):
    path, repository = catalogue
    repository.save(rich_metadata, tmp_path, "Album/CD 1/one.flac")
    root, relative, metadata = (
        tmp_path,
        "Album/CD 2/two.flac",
        replace(rich_metadata, disc_number=2),
    )
    if difference == "folder":
        relative = "Other/CD 2/two.flac"
    elif difference == "library":
        root = tmp_path / "Other library"
    elif difference == "year":
        metadata = replace(metadata, album_year=2021)
    elif difference == "artists":
        metadata = replace(metadata, album_artists=("Other",))
    elif difference == "date":
        metadata = replace(metadata, album_date="2020-05-04")
    elif difference == "unnumbered-disc":
        metadata = replace(metadata, disc_number=None)
    else:
        metadata = replace(metadata, disc_number=3)
    repository.save(metadata, root, relative)
    assert len(albums(path)) == 2


def test_missing_album_artists_does_not_split_a_compilation(catalogue, rich_metadata, tmp_path):
    path, repository = catalogue
    for number, artist in enumerate(("First", "Second"), 1):
        repository.save(
            replace(rich_metadata, album_artists=(), artists=(artist,), track_number=number),
            tmp_path,
            f"Compilation/{number}.flac",
        )
    result = albums(path)
    assert len(result) == 1 and result[0].artists == ()


def test_album_common_edits_preserve_track_artists_and_other_editions(
    catalogue, rich_metadata, tmp_path
):
    path, repository = catalogue
    entries = tuple(
        repository.save(
            replace(rich_metadata, artists=(artist,), track_number=number),
            tmp_path,
            f"Album/{number}.flac",
        )
        for number, artist in enumerate(("First", "Second"), 1)
    )
    other = repository.save(rich_metadata, tmp_path, "Other/one.flac")
    originals = tuple(editable(path, entry.file_id) for entry in entries)
    result = UpdateCatalogTracks(SqliteCatalogEditSessionFactory()).execute(
        path,
        originals,
        patch(
            album="Renamed", album_year=2022, album_artists=("Various Artists",), genres=("Rock",)
        ),
    )
    assert len(result) == 2
    for index, entry in enumerate(entries):
        actual = repository.get(entry.file_id).metadata
        assert actual.album == "Renamed" and actual.album_year == 2022
        assert actual.album_artists == ("Various Artists",)
        assert actual.artists == ("First" if index == 0 else "Second",)
        assert actual.title == rich_metadata.title and actual.lyrics == rich_metadata.lyrics
    assert repository.get(other.file_id).metadata == rich_metadata
    assert len(albums(path)) == 2


def test_album_edit_conflict_rolls_back_every_track(catalogue, rich_metadata, tmp_path):
    path, repository = catalogue
    entries = tuple(
        repository.save(rich_metadata, tmp_path, f"Album/{number}.flac") for number in (1, 2)
    )
    originals = tuple(editable(path, entry.file_id) for entry in entries)
    edit(path, entries[1].file_id, title="Concurrent correction")
    with pytest.raises(CatalogEditConflict):
        UpdateCatalogTracks(SqliteCatalogEditSessionFactory()).execute(
            path,
            originals,
            patch(album_artists=("New artist",)),
        )
    assert all(
        repository.get(entry.file_id).metadata.album_artists == ("Abbath",) for entry in entries
    )
    assert repository.get(entries[1].file_id).metadata.title == "Concurrent correction"


@pytest.mark.parametrize("kind", ["flac", "mp3"])
def test_album_artist_names_round_trip_in_audio_without_touching_track_artists(
    catalogue, tmp_path, kind
):
    from test_tag_write import make_source

    from trackfolio.application.write_tags import TagWriteService
    from trackfolio.infrastructure.metadata import read_metadata
    from trackfolio.infrastructure.tag_write import MutagenTagCodec
    from trackfolio.infrastructure.tag_write_catalog import SqliteTagCatalog
    from trackfolio.infrastructure.tag_write_files import FileTagAccess

    database, repository = catalogue
    source = make_source(tmp_path, kind)
    entry = repository.save(read_metadata(source), source.parent, source.name)
    old_artists = read_metadata(source).artists
    names = ("AC/DC", "Artist; complete name")
    edit(database, entry.file_id, album_artists=names)
    service = TagWriteService(
        SqliteTagCatalog(), MutagenTagCodec(), FileTagAccess(tmp_path / "operations")
    )
    report = service.execute(database, (entry.file_id,))
    assert report.results[0].state == "confirmed", report
    actual = read_metadata(source)
    assert actual.album_artists == names and actual.artists == old_artists
    edit(database, entry.file_id, album_artists=())
    assert service.execute(database, (entry.file_id,)).results[0].state == "confirmed"
    assert read_metadata(source).album_artists == ()
