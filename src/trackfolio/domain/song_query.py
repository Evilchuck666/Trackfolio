"""Advanced song search: words, "phrases", /regex/, field:a,b lists, flags and sort: order."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, cast

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
# Sort keys match the song table columns; None marks a missing value (always listed last).
SORT_KEYS: dict[str, Callable[[CatalogSummary], str | int | None]] = {
    "title": lambda row: (row.title or "").casefold() or None,
    "artist": lambda row: "; ".join(row.artists).casefold() or None,
    "album": lambda row: (row.album or "").casefold() or None,
    "year": lambda row: row.album_year,
    "path": lambda row: row.relative_path.casefold() or None,
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
    FilterHelp("title:", "title:intro", "Whole song title (like SQL LIKE)"),
    FilterHelp("artist:", 'artist:"Daft Punk"', "Whole name of any track artist"),
    FilterHelp("album:", "album:/^greatest/i", "Whole album title, or a /regex/"),
    FilterHelp("genre:", "genre:metal", "Whole name of any genre"),
    FilterHelp("path:", "path:%.flac", "Whole file path inside the library"),
    FilterHelp("field:a%", "title:%live%", "% matches any text: abb% starts with, %live% contains"),
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
    FilterHelp("field:a,b", "genre:metal,rock", "Any of several values (IN) for any field above"),
    FilterHelp("-term or !term", "-has:lyrics", "Negate any term; -genre:pop,dance is NOT IN"),
    FilterHelp("sort:field", "sort:year", "Order by title, artist, album, year or path"),
    FilterHelp("sort:-field", "sort:artist,-year", "Descending order; several keys with commas"),
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
    name, colon, value = body.partition(":")
    name = name.lower()
    if not colon:
        options = [
            *(f"{field}:" for field in (*TEXT_FIELDS, "year")),
            *(f"has:{flag}" for flag in FLAGS),
            *(f"is:{flag}" for flag in IS_FLAGS),
            *(() if sign else ("sort:",)),
        ]
    else:
        values: tuple[str, ...]
        if name == "has":
            values = tuple(FLAGS)
        elif name == "is":
            values = tuple(IS_FLAGS)
        elif name == "year":
            values = tuple(str(year) for year in years)
        elif name == "sort":
            values = (*SORT_KEYS, *(f"-{key}" for key in SORT_KEYS))
        else:
            values = {"genre": genres, "artist": artists, "album": albums}.get(name, ())
        # After a comma, suggest the next value of the list, skipping those already listed.
        head, comma, _last = value.rpartition(",")
        lead = f"{name}:{head}," if comma else f"{name}:"
        listed = {item.strip('"').casefold() for item in head.split(",")} if comma else set()
        options = [
            lead + (f'"{v}"' if any(c.isspace() for c in v) else v)
            for v in values
            if v.casefold() not in listed
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
class SortKey:
    field: str
    descending: bool = False


@dataclass(frozen=True, slots=True)
class SongQuery:
    terms: tuple[_Term, ...] = ()
    order: tuple[SortKey, ...] = ()
    # Where the sort: term sits in the parsed text, so column headers can rewrite it.
    sort_span: tuple[int, int] | None = None

    @property
    def is_empty(self) -> bool:
        """True when nothing is filtered; sort: alone only changes the order."""
        return not self.terms

    def matches(self, row: CatalogSummary) -> bool:
        return all(term.matches(row) for term in self.terms)

    def sort(self, rows: tuple[CatalogSummary, ...]) -> tuple[CatalogSummary, ...]:
        """Order by the sort: keys; ties and the default keep the given (catalog) order."""
        ordered = list(rows)
        # Stable passes from the least to the most significant key give lexicographic order.
        for key in reversed(self.order):
            value = SORT_KEYS[key.field]
            present = [row for row in ordered if value(row) is not None]
            missing = [row for row in ordered if value(row) is None]
            present.sort(key=lambda row: cast(Any, value(row)), reverse=key.descending)
            ordered = present + missing
        return tuple(ordered)


def with_sort(text: str, query: SongQuery, value: str | None) -> str:
    """Replace, add or (with None) remove the sort: term of ``text`` parsed as ``query``."""
    term = f"sort:{value}" if value else ""
    if query.sort_span is not None:
        start, end = query.sort_span
        before, after = text[:start].rstrip(), text[end:].lstrip()
        return " ".join(part for part in (before, term, after) if part)
    return " ".join(part for part in (text.strip(), term) if part)


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
    at_end = index + 1 >= len(text) or text[index + 1].isspace() or text[index + 1] == ","
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


def _read_items(
    text: str, index: int, *, rich: bool
) -> tuple[list[tuple[int, str | re.Pattern[str]]], int]:
    """Comma-separated field values; ``rich`` values may also be "phrases" or /regex/."""
    items: list[tuple[int, str | re.Pattern[str]]] = []
    while True:
        start = index
        value: str | re.Pattern[str]
        if rich and index < len(text) and text[index] == '"':
            value, index = _read_quoted(text, index)
        elif rich and index < len(text) and text[index] == "/":
            value, index = _read_regex(text, index)
        else:
            while index < len(text) and not text[index].isspace() and text[index] != ",":
                index += 1
            value = text[start:index]
        items.append((start, value))
        if index < len(text) and text[index] == ",":
            index += 1
            if index >= len(text) or text[index].isspace() or text[index] == ",":
                raise SongQueryError("Missing value after ,.", index)
            continue
        return items, index


def _any(tests: list[Callable[[CatalogSummary], bool]]) -> Callable[[CatalogSummary], bool]:
    if len(tests) == 1:
        return tests[0]
    return lambda row: any(test(row) for test in tests)


def _like_test(
    value: str | re.Pattern[str], fields: Callable[[CatalogSummary], tuple[str, ...]]
) -> Callable[[CatalogSummary], bool]:
    """Field values match whole, like SQL LIKE: % is any text; /regex/ keeps searching."""
    if isinstance(value, re.Pattern):
        return _text_test(value, fields)
    pattern = re.compile(
        ".*".join(re.escape(part) for part in value.casefold().split("%")), re.DOTALL
    )
    return lambda row: any(pattern.fullmatch(item.casefold()) for item in fields(row))


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
    """Parse the search box: all terms must match (AND); a field:a,b list matches any value."""
    terms: list[_Term] = []
    order: tuple[SortKey, ...] = ()
    sort_span: tuple[int, int] | None = None
    index = 0
    while index < len(text):
        if text[index].isspace():
            index += 1
            continue
        start = index
        negated = text[index] in "-!" and index + 1 < len(text) and not text[index + 1].isspace()
        if negated:
            index += 1
        test: Callable[[CatalogSummary], bool] | None = None
        if text[index] == '"':
            phrase, index = _read_quoted(text, index)
            test = _text_test(phrase, _default_text)
        elif text[index] == "/":
            pattern, index = _read_regex(text, index)
            test = _text_test(pattern, _default_text)
        else:
            field = re.match(r"([A-Za-z]+):", text[index:])
            known = (*TEXT_FIELDS, "has", "is", "year", "sort")
            if field is None or field.group(1).lower() not in known:
                word, index = _read_word(text, index)
                test = _text_test(word, _default_text)
            else:
                name = field.group(1).lower()
                index += field.end()
                value_start = index
                items, index = _read_items(text, index, rich=name in TEXT_FIELDS)
                if name in ("has", "is"):
                    flags = FLAGS if name == "has" else IS_FLAGS
                    tests = []
                    for position, flag in items:
                        flag = str(flag)
                        if flag.lower() not in flags:
                            raise SongQueryError(
                                f"Unknown flag {name}:{flag}. Use one of: {', '.join(flags)}.",
                                position,
                            )
                        tests.append(flags[flag.lower()])
                    test = _any(tests)
                elif name == "year":
                    test = _any([_year_test(str(value), position) for position, value in items])
                elif name == "sort":
                    if negated:
                        raise SongQueryError("sort: cannot be negated.", start)
                    if sort_span is not None:
                        raise SongQueryError("Use a single sort: term.", start)
                    keys = []
                    for position, item in items:
                        item = str(item)
                        key = item.removeprefix("-").lower()
                        if key not in SORT_KEYS:
                            raise SongQueryError(
                                f"Unknown sort key {item or '(empty)'}. "
                                f"Use one of: {', '.join(SORT_KEYS)}.",
                                position,
                            )
                        keys.append(SortKey(key, item.startswith("-")))
                    order, sort_span = tuple(keys), (start, index)
                else:
                    if items[0][1] == "":
                        raise SongQueryError(f"Missing value after {name}:.", value_start)
                    test = _any([_like_test(value, TEXT_FIELDS[name]) for _, value in items])
        if index < len(text) and not text[index].isspace():
            raise SongQueryError("Expected a space between search terms.", index)
        if test is not None:
            terms.append(_Term(test, negated))
    return SongQuery(tuple(terms), order, sort_span)
