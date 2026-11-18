"""Advanced song search syntax, independent of Qt."""

import pytest

from trackfolio.domain.catalog import CatalogSummary
from trackfolio.domain.song_query import SongQueryError, parse_song_query

ROWS = (
    CatalogSummary(
        1,
        11,
        "First song",
        ("Björk",),
        "Debut",
        1993,
        "Björk/a.flac",
        ("Pop", "Jazz"),
        has_lyrics=True,
        has_cover=True,
        is_instrumental=True,
    ),
    CatalogSummary(2, 12, "Second song (Live)", ("Accept",), "Breaker", 1981, "b.flac", ("Metal",)),
    CatalogSummary(3, 13, None, (), None, None, "c.mp3", has_cover=True),
)


def ids(text):
    query = parse_song_query(text)
    return tuple(row.file_id for row in ROWS if query.matches(row))


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("", (1, 2, 3)),
        ("   ", (1, 2, 3)),
        ("BJÖRK debut", (1,)),
        ("song", (1, 2)),
        ('"second song"', (2,)),
        ('"song debut"', ()),
        ("/^first/i", (1,)),
        ("/^first/", ()),
        (r"/\(live\)$/i", (2,)),
        ("-/live/i", (1, 3)),
        ("title:first%", (1,)),
        ("title:first", ()),
        ('title:"first song"', (1,)),
        ("title:%song%", (1, 2)),
        ("title:%(live)", (2,)),
        ("title:%(live", ()),
        ("artist:accept", (2,)),
        ('album:"debut"', (1,)),
        ('album:"deb"', ()),
        ("genre:/^j/i", (1,)),
        ("path:%.mp3", (3,)),
        ("path:.mp3", ()),
        ("path:%a.flac", (1,)),
        ("path:%x.flac", ()),
        ("year:1993", (1,)),
        ("year:1980..1990", (2,)),
        ("year:1990..", (1,)),
        ("year:..1990", (2,)),
        ("year:>=1981", (1, 2)),
        ("year:<1990", (2,)),
        ("has:lyrics", (1,)),
        ("-has:lyrics", (2, 3)),
        ("!has:lyrics", (2, 3)),
        ("has:cover -has:year", (3,)),
        ("has:genre", (1, 2)),
        ("-has:artist", (3,)),
        ("HAS:Album Title:%SONG%", (1, 2)),
        ("genre:metal,jazz", (1, 2)),
        ("-genre:metal,jazz", (3,)),
        ('artist:accept,"björk"', (1, 2)),
        ("album:/^deb/i,/^break/i", (1, 2)),
        ("year:1981,1990..1999", (1, 2)),
        ("has:lyrics,cover", (1, 3)),
        ("-has:lyrics,cover", (2,)),
        ("path:%.flac,%.mp3", (1, 2, 3)),
        ("title:first%,second% path:%.mp3", ()),
        ("genre:met%,jazz", (1, 2)),
        ("-artist:accept", (1, 3)),
        ("a,b", ()),
        ("sort:-year", (1, 2, 3)),
        ("song sort:title", (1, 2)),
        ("is:instrumental", (1,)),
        ("-is:instrumental", (2, 3)),
        ("IS:Instrumental song", (1,)),
        ("-", ()),
        ("re:zero", ()),
        ("AC/DC", ()),
    ],
)
def test_query_matches(text, expected):
    assert ids(text) == expected


@pytest.mark.parametrize(
    ("text", "message", "position"),
    [
        ("/[/", "Invalid regular expression", 0),
        ("/abc", "Unclosed regular expression", 0),
        ("//", "Empty regular expression", 0),
        ('"open', "Unclosed quote", 0),
        ("ok has:nope", "Unknown flag has:nope", 7),
        ("year:abc", "Invalid year filter", 5),
        ("is:lyrics", "Unknown flag is:lyrics", 3),
        ("genre:metal,", "Missing value after ,", 12),
        ("genre:metal,,rock", "Missing value after ,", 12),
        ("genre:,rock", "Missing value after genre:", 6),
        ("has:lyrics,nope", "Unknown flag has:nope", 11),
        ("year:1981,abc", "Invalid year filter", 10),
        ("album:/a/i,/b", "Unclosed regular expression", 11),
        ("sort:foo", "Unknown sort key foo", 5),
        ("sort:", r"Unknown sort key \(empty\)", 5),
        ("sort:year,-nope", "Unknown sort key -nope", 10),
        ("-sort:year", "sort: cannot be negated", 0),
        ("sort:year sort:title", "Use a single sort: term", 10),
        ("year:", "Invalid year filter", 5),
        ("artist:", "Missing value after artist:", 7),
        ('"a"b', "Expected a space", 3),
        ("/a/x", "Expected a space", 3),
    ],
)
def test_invalid_queries_report_message_and_position(text, message, position):
    with pytest.raises(SongQueryError, match=message) as info:
        parse_song_query(text)
    assert info.value.position == position


def test_empty_query_flag():
    assert parse_song_query("  ").is_empty
    assert not parse_song_query("has:lyrics").is_empty


def test_reference_documents_every_field_and_flag():
    from trackfolio.domain.song_query import (
        FILTER_REFERENCE,
        FLAGS,
        IS_FLAGS,
        SYNTAX_HELP,
        TEXT_FIELDS,
    )

    syntaxes = {item.syntax for item in FILTER_REFERENCE}
    assert {f"{field}:" for field in TEXT_FIELDS} <= syntaxes
    assert {f"has:{flag}" for flag in FLAGS} <= syntaxes
    assert {f"is:{flag}" for flag in IS_FLAGS} <= syntaxes
    for item in FILTER_REFERENCE:
        parse_song_query(item.example)
        assert item.syntax in SYNTAX_HELP


@pytest.mark.parametrize(
    ("prefix", "expected"),
    [
        (
            "ha",
            [
                "has:lyrics",
                "has:cover",
                "has:genre",
                "has:year",
                "has:artist",
                "has:album",
                "has:title",
            ],
        ),
        ("ye", ["year:"]),
        ("so", ["sort:"]),
        ("-so", []),
        ("sort:-y", ["sort:-year"]),
        ("sort:year,ar", ["sort:year,artist"]),
        ("genre:jazz,", ['genre:jazz,"Hip Hop"']),
        ("genre:jazz,h", ['genre:jazz,"Hip Hop"']),
        ("is", ["is:instrumental"]),
        ("-is:i", ["-is:instrumental"]),
        ("-has:l", ["-has:lyrics"]),
        ("!HAS:c", ["!has:cover"]),
        ("genre:", ["genre:Jazz", 'genre:"Hip Hop"']),
        ('genre:"hip', ['genre:"Hip Hop"']),
        ("artist:b", ["artist:Björk"]),
        ("year:19", ["year:1993", "year:1981"]),
        ("path:", []),
        ("zzz", []),
    ],
)
def test_completion_candidates(prefix, expected):
    from trackfolio.domain.song_query import completion_candidates

    assert (
        completion_candidates(
            prefix, ("Jazz", "Hip Hop"), ("Björk", "Accept"), ("Debut",), (1993, 1981)
        )
        == expected
    )


def order(text, rows=ROWS):
    return tuple(row.file_id for row in parse_song_query(text).sort(rows))


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("", (1, 2, 3)),
        ("sort:title", (1, 2, 3)),
        ("sort:-title", (2, 1, 3)),
        ("sort:year", (2, 1, 3)),
        ("sort:-year", (1, 2, 3)),
        ("sort:artist", (2, 1, 3)),
        ("sort:-artist", (1, 2, 3)),
        ("sort:path", (2, 1, 3)),
        ("SORT:YEAR", (2, 1, 3)),
    ],
)
def test_sort_orders_rows_with_missing_values_last(text, expected):
    assert order(text) == expected


def test_sort_combines_keys_and_keeps_catalog_order_for_ties():
    rows = (
        CatalogSummary(5, 1, "b", ("Zed",), None, 2000, "5.flac"),
        CatalogSummary(2, 2, "a", ("abba",), None, None, "2.flac"),
        CatalogSummary(9, 3, "c", ("Abba",), None, 2001, "9.flac"),
        CatalogSummary(4, 4, "d", ("ABBA",), None, 2001, "4.flac"),
    )
    assert order("sort:artist,-year", rows) == (9, 4, 2, 5)
    assert order("sort:artist", rows) == (2, 9, 4, 5)
    assert order("sort:-year,title", rows) == (9, 4, 5, 2)
    assert order("genre:x", rows) == (5, 2, 9, 4)


def test_sort_span_and_rewriting_the_sort_term():
    from trackfolio.domain.song_query import SortKey, with_sort

    text = "rock  sort:artist,-year  live"
    query = parse_song_query(text)
    assert query.order == (SortKey("artist"), SortKey("year", True))
    assert query.sort_span == (6, 23)
    assert not query.is_empty
    assert parse_song_query("sort:year").is_empty
    assert with_sort(text, query, "-title") == "rock sort:-title live"
    assert with_sort(text, query, None) == "rock live"
    assert with_sort("rock ", parse_song_query("rock "), "year") == "rock sort:year"
    assert with_sort("", parse_song_query(""), "year") == "sort:year"
    assert with_sort("sort:year", parse_song_query("sort:year"), None) == ""


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("artist:abbath", ("Abbath",)),
        ("artist:ABBATH", ("Abbath",)),
        ("artist:abb%", ("Abbath",)),
        ("artist:%sabbath", ("Black Sabbath",)),
        ("artist:%abbath", ("Abbath", "Black Sabbath")),
        ('artist:"black sabbath"', ("Black Sabbath",)),
        ("artist:black", ()),
        ("artist:black%", ("Black Sabbath",)),
        ("-artist:abbath", ("Black Sabbath", "Ghost_B.C.")),
        ("artist:ghost_b.c.", ("Ghost_B.C.",)),
        ("artist:ghostxbxc.", ()),
        ("artist:%", ("Abbath", "Black Sabbath", "Ghost_B.C.")),
        ("abbath", ("Abbath", "Black Sabbath")),
    ],
)
def test_field_values_match_whole_like_sql_like(text, expected):
    rows = tuple(
        CatalogSummary(index, index, "Song", (name,), None, None, f"{index}.flac")
        for index, name in enumerate(("Abbath", "Black Sabbath", "Ghost_B.C."), 1)
    )
    query = parse_song_query(text)
    assert tuple(row.artists[0] for row in rows if query.matches(row)) == expected
