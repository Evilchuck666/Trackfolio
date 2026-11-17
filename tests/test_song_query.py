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
        ("title:first", (1,)),
        ("artist:accept", (2,)),
        ('album:"deb"', (1,)),
        ("genre:/^j/i", (1,)),
        ("path:.mp3", (3,)),
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
        ("HAS:Album Title:SONG", (1, 2)),
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
    from trackfolio.domain.song_query import FILTER_REFERENCE, FLAGS, SYNTAX_HELP, TEXT_FIELDS

    syntaxes = {item.syntax for item in FILTER_REFERENCE}
    assert {f"{field}:" for field in TEXT_FIELDS} <= syntaxes
    assert {f"has:{flag}" for flag in FLAGS} <= syntaxes
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
