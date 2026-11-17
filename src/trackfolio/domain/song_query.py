"""Advanced song search: words, "phrases", /regex/, field:value, year ranges and has: flags."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass

from trackfolio.domain.catalog import CatalogSummary

TEXT_FIELDS: dict[str, Callable[[CatalogSummary], tuple[str, ...]]] = {
    "title": lambda row: (row.title or "",),
    "artist": lambda row: row.artists,
    "album": lambda row: (row.album or "",),
    "genre": lambda row: row.genres,
    "path": lambda row: (row.relative_path,),
}
FLAGS: dict[str, Callable[[CatalogSummary], bool]] = {
    "lyrics": lambda row: row.has_lyrics,
    "cover": lambda row: row.has_cover,
    "genre": lambda row: bool(row.genres),
    "year": lambda row: row.album_year is not None,
    "artist": lambda row: bool(row.artists),
    "album": lambda row: bool(row.album),
    "title": lambda row: bool(row.title),
}
IS_FLAGS: dict[str, Callable[[CatalogSummary], bool]] = {
    "instrumental": lambda row: row.is_instrumental,
}


@dataclass(frozen=True, slots=True)
class FilterHelp:
    syntax: str
    example: str
    description: str


FILTER_REFERENCE: tuple[FilterHelp, ...] = (
    FilterHelp("word", "song", "Title, artist or album contains the word"),
    FilterHelp('"phrase"', '"second song"', "Title, artist or album contains the phrase"),
    FilterHelp("/regex/", "/^The /", "Regular expression, case sensitive"),
    FilterHelp("/regex/i", "/live/i", "Regular expression, ignoring case"),
    FilterHelp("title:", "title:intro", "Song title"),
    FilterHelp("artist:", 'artist:"Daft Punk"', "Any track artist"),
    FilterHelp("album:", "album:/^greatest/i", "Album title"),
    FilterHelp("genre:", "genre:metal", "Any genre"),
    FilterHelp("path:", "path:.flac", "File path inside the library"),
    FilterHelp("year:N", "year:1993", "Exact album year"),
    FilterHelp("year:A..B", "year:1990..1999", "Album year range (either end optional)"),
    FilterHelp("year:>N", "year:>=2000", "Album year compared with >, >=, < or <="),
    FilterHelp("has:lyrics", "has:lyrics", "Songs with lyrics"),
    FilterHelp("has:cover", "has:cover", "Songs with a cover image"),
    FilterHelp("has:genre", "has:genre", "Songs with at least one genre"),
    FilterHelp("has:year", "has:year", "Songs with an album year"),
    FilterHelp("has:artist", "has:artist", "Songs with at least one artist"),
    FilterHelp("has:album", "has:album", "Songs with an album"),
    FilterHelp("has:title", "has:title", "Songs with a title"),
    FilterHelp("is:instrumental", "is:instrumental", "Songs marked as instrumental"),
    FilterHelp("-term or !term", "-has:lyrics", "Negate any term"),
)
SYNTAX_HELP = "\n".join(f"{item.syntax:<16} {item.description}" for item in FILTER_REFERENCE) + (
    "\nAll terms must match."
)


def completion_candidates(
    prefix: str,
    genres: tuple[str, ...] = (),
    artists: tuple[str, ...] = (),
    albums: tuple[str, ...] = (),
    years: tuple[int, ...] = (),
) -> list[str]:
    """Suggestions for the term being typed; each starts with ``prefix`` (case-insensitive)."""
    sign = prefix[:1] if prefix[:1] in "-!" else ""
    body = prefix[len(sign) :]
    name, colon, _value = body.partition(":")
    name = name.lower()
    if not colon:
        options = [
            *(f"{field}:" for field in (*TEXT_FIELDS, "year")),
            *(f"has:{flag}" for flag in FLAGS),
            *(f"is:{flag}" for flag in IS_FLAGS),
        ]
    else:
        values: tuple[str, ...]
        if name == "has":
            values = tuple(FLAGS)
        elif name == "is":
            values = tuple(IS_FLAGS)
        elif name == "year":
            values = tuple(str(year) for year in years)
        else:
            values = {"genre": genres, "artist": artists, "album": albums}.get(name, ())
        options = [
            f'{name}:"{v}"' if any(c.isspace() for c in v) else f"{name}:{v}" for v in values
        ]
    folded = body.replace('"', "").casefold()
    return [
        sign + option for option in options if option.replace('"', "").casefold().startswith(folded)
    ]


class SongQueryError(ValueError):
    def __init__(self, message: str, position: int) -> None:
        super().__init__(message)
        self.position = position


def _default_text(row: CatalogSummary) -> tuple[str, ...]:
    return (row.title or "", *row.artists, row.album or "")


@dataclass(frozen=True, slots=True)
class _Term:
    test: Callable[[CatalogSummary], bool]
    negated: bool

    def matches(self, row: CatalogSummary) -> bool:
        return self.test(row) != self.negated


@dataclass(frozen=True, slots=True)
class SongQuery:
    terms: tuple[_Term, ...] = ()

    @property
    def is_empty(self) -> bool:
        return not self.terms

    def matches(self, row: CatalogSummary) -> bool:
        return all(term.matches(row) for term in self.terms)


def _read_quoted(text: str, start: int) -> tuple[str, int]:
    end = text.find('"', start + 1)
    if end < 0:
        raise SongQueryError("Unclosed quote.", start)
    return text[start + 1 : end], end + 1


def _read_regex(text: str, start: int) -> tuple[re.Pattern[str], int]:
    index = start + 1
    while index < len(text):
        if text[index] == "\\":
            index += 2
            continue
        if text[index] == "/":
            break
        index += 1
    else:
        raise SongQueryError("Unclosed regular expression.", start)
    source = text[start + 1 : index]
    index += 1
    flags = 0
    at_end = index + 1 >= len(text) or text[index + 1].isspace()
    if index < len(text) and text[index] == "i" and at_end:
        flags = re.IGNORECASE
        index += 1
    if not source:
        raise SongQueryError("Empty regular expression.", start)
    try:
        return re.compile(source, flags), index
    except re.error as exc:
        raise SongQueryError(f"Invalid regular expression: {exc.msg}.", start) from exc


def _read_word(text: str, start: int) -> tuple[str, int]:
    index = start
    while index < len(text) and not text[index].isspace():
        index += 1
    return text[start:index], index


def _text_test(
    value: str | re.Pattern[str], fields: Callable[[CatalogSummary], tuple[str, ...]]
) -> Callable[[CatalogSummary], bool]:
    if isinstance(value, re.Pattern):
        return lambda row: any(value.search(item) for item in fields(row))
    needle = value.casefold()
    return lambda row: any(needle in item.casefold() for item in fields(row))


_YEAR = re.compile(
    r"(?:(?P<op>>=|<=|>|<|=)?(?P<year>\d{1,4})|(?P<low>\d{1,4})?\.\.(?P<high>\d{1,4})?)"
)


def _year_test(value: str, position: int) -> Callable[[CatalogSummary], bool]:
    match = _YEAR.fullmatch(value)
    if match is None or (match["year"] is None and match["low"] is None and match["high"] is None):
        raise SongQueryError(f"Invalid year filter: {value or '(empty)'}.", position)
    if match["year"] is not None:
        year = int(match["year"])
        compare: Callable[[int], bool] = {
            None: lambda item: item == year,
            "=": lambda item: item == year,
            ">": lambda item: item > year,
            ">=": lambda item: item >= year,
            "<": lambda item: item < year,
            "<=": lambda item: item <= year,
        }[match["op"]]
    else:
        low = int(match["low"]) if match["low"] else None
        high = int(match["high"]) if match["high"] else None
        compare = lambda item: (low is None or item >= low) and (high is None or item <= high)  # noqa: E731
    return lambda row: row.album_year is not None and compare(row.album_year)


def parse_song_query(text: str) -> SongQuery:
    """Parse the search box; all terms must match (AND)."""
    terms: list[_Term] = []
    index = 0
    while index < len(text):
        if text[index].isspace():
            index += 1
            continue
        start = index
        negated = text[index] in "-!" and index + 1 < len(text) and not text[index + 1].isspace()
        if negated:
            index += 1
        test: Callable[[CatalogSummary], bool]
        if text[index] == '"':
            phrase, index = _read_quoted(text, index)
            test = _text_test(phrase, _default_text)
        elif text[index] == "/":
            pattern, index = _read_regex(text, index)
            test = _text_test(pattern, _default_text)
        else:
            field = re.match(r"([A-Za-z]+):", text[index:])
            if field is None or field.group(1).lower() not in (*TEXT_FIELDS, "has", "is", "year"):
                word, index = _read_word(text, index)
                test = _text_test(word, _default_text)
            else:
                name = field.group(1).lower()
                index += field.end()
                value_start = index
                if name in ("has", "is"):
                    flags = FLAGS if name == "has" else IS_FLAGS
                    flag, index = _read_word(text, index)
                    if flag.lower() not in flags:
                        raise SongQueryError(
                            f"Unknown flag {name}:{flag}. Use one of: {', '.join(flags)}.",
                            value_start,
                        )
                    test = flags[flag.lower()]
                elif name == "year":
                    value, index = _read_word(text, index)
                    test = _year_test(value, value_start)
                elif name in TEXT_FIELDS:
                    if index < len(text) and text[index] == '"':
                        phrase, index = _read_quoted(text, index)
                        test = _text_test(phrase, TEXT_FIELDS[name])
                    elif index < len(text) and text[index] == "/":
                        pattern, index = _read_regex(text, index)
                        test = _text_test(pattern, TEXT_FIELDS[name])
                    else:
                        value, index = _read_word(text, index)
                        if not value:
                            raise SongQueryError(f"Missing value after {name}:.", value_start)
                        test = _text_test(value, TEXT_FIELDS[name])
                else:  # pragma: no cover - excluded by the field check above
                    raise SongQueryError(f"Unknown field {name}:.", start)
        if index < len(text) and not text[index].isspace():
            raise SongQueryError("Expected a space between search terms.", index)
        terms.append(_Term(test, negated))
    return SongQuery(tuple(terms))
