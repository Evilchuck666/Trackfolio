"""Artist grouping keeps editions intact and uses conservative fallback credits."""

from dataclasses import replace

from test_albums import albums
from test_catalog_edit import catalogue as catalogue
from test_catalog_edit import rich_metadata as rich_metadata

from trackfolio.application.artists import group_artists


def test_album_credits_take_priority_and_collaborations_share_editions(
    catalogue, rich_metadata, tmp_path
):
    path, repository = catalogue
    repository.save(
        replace(rich_metadata, album_artists=("First", "Second"), artists=("Guest",)),
        tmp_path,
        "Album/one.flac",
    )
    editions = albums(path)
    groups = group_artists(editions)
    assert tuple(groups) == ("First", "Second")
    assert groups["First"] == groups["Second"] == editions


def test_fallback_and_unknown_artist_keep_compilations_intact(catalogue, rich_metadata, tmp_path):
    path, repository = catalogue
    for folder, artists in (
        ("Solo", ("Solo",)),
        ("Mixed", ("One",)),
        ("Mixed", ("Two",)),
        ("Empty", ()),
    ):
        repository.save(
            replace(rich_metadata, album_artists=(), artists=artists),
            tmp_path,
            f"{folder}/{artists}.flac",
        )
    groups = group_artists(albums(path))
    assert tuple(groups) == ("Solo", None)
    assert len(groups["Solo"]) == 1
    assert len(groups[None]) == 2


def test_editions_order_by_year_and_preserve_distinct_folders(catalogue, rich_metadata, tmp_path):
    path, repository = catalogue
    for folder, year in (("Later", 2020), ("Earlier", 1980), ("Reissue", 2020)):
        repository.save(replace(rich_metadata, album_year=year), tmp_path, f"{folder}/one.flac")
    editions = group_artists(albums(path))["Abbath"]
    assert [a.year for a in editions] == [1980, 2020, 2020]
    assert len({a.directory for a in editions}) == 3
