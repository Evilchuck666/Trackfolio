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
SYNTAX_HELP = (
    'word · "exact phrase" · /regex/ or /regex/i\n'
    'title: artist: album: genre: path: (word, "phrase" or /regex/)\n'
    "year:1993 · year:1990..1999 · year:>=2000 · year:<1980\n"
    "has:lyrics has:cover has:genre has:year has:artist has:album has:title\n"
    "Prefix - or ! to negate: -has:lyrics, -artist:accept, -/live/i"
)


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
            if field is None or field.group(1).lower() not in (*TEXT_FIELDS, "has", "year"):
                word, index = _read_word(text, index)
                test = _text_test(word, _default_text)
            else:
                name = field.group(1).lower()
                index += field.end()
                value_start = index
                if name == "has":
                    flag, index = _read_word(text, index)
                    if flag.lower() not in FLAGS:
                        raise SongQueryError(
                            f"Unknown flag has:{flag}. Use one of: {', '.join(FLAGS)}.", value_start
                        )
                    test = FLAGS[flag.lower()]
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
