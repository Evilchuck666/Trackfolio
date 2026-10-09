"""Read FLAC/MP3 metadata without changing music files or requiring a desktop."""

from __future__ import annotations

import math
import re
import struct
from collections.abc import Callable, Iterable, Sequence
from datetime import date, datetime
from pathlib import Path
from typing import Protocol, cast

import mutagen
from mutagen.flac import FLAC
from mutagen.id3 import ID3, ID3NoHeaderError
from mutagen.mp3 import MP3

from trackfolio.application.catalog import MetadataReadError, UnsupportedAudioError
from trackfolio.domain.metadata import Artwork, RawTagValue, TrackMetadata

__all__ = ["MetadataReadError", "UnsupportedAudioError", "read_metadata"]


class _Picture(Protocol):
    type: int
    data: bytes
    width: int
    height: int


class _FlacFile(Protocol):
    tags: Iterable[tuple[str, str]] | None
    pictures: Sequence[_Picture]
    info: object


class _Id3Tags(Protocol):
    def items(self) -> Iterable[tuple[str, object]]: ...


class _Mp3File(Protocol):
    info: object


def _canonical_key(key: str) -> str:
    key = key.casefold()
    if key.startswith("txxx:"):
        key = key[5:]
    elif key.startswith(("uslt:", "comm:")):
        key = key.split(":", 1)[0]
    return re.sub(r"[ _-]", "", key)


def _raw_values(entries: Iterable[tuple[str, str]]) -> tuple[RawTagValue, ...]:
    positions: dict[str, int] = {}
    result = []
    for key, value in entries:
        position = positions.get(key, 0)
        result.append(RawTagValue(key=key, value=value, position=position))
        positions[key] = position + 1
    return tuple(result)


def _values(tags: tuple[RawTagValue, ...], *aliases: str) -> tuple[str, ...]:
    """Prefer the first populated alias without splitting artist/genre names."""
    for alias in aliases:
        result = tuple(
            tag.value for tag in tags if _canonical_key(tag.key) == alias and tag.value.strip()
        )
        if result:
            return result
    return ()


def _first(tags: tuple[RawTagValue, ...], *aliases: str) -> str | None:
    values = _values(tags, *aliases)
    return values[0] if values else None


def _positive_number(value: str | None) -> int | None:
    if value is None or not re.fullmatch(r"[0-9]+", value.strip()):
        return None
    try:
        number = int(value.strip())
    except ValueError:
        return None
    return number if number > 0 else None


def _number_pair(value: str | None, separate_total: str | None) -> tuple[int | None, int | None]:
    if value is None:
        return None, _positive_number(separate_total)
    components = value.split("/")
    if len(components) > 2:
        return None, _positive_number(separate_total)
    number = _positive_number(components[0])
    fraction_total = _positive_number(components[1]) if len(components) == 2 else None
    return number, _positive_number(separate_total) or fraction_total


def _year(value: str | None) -> int | None:
    if value is None:
        return None
    value = value.strip()
    try:
        if re.fullmatch(r"[0-9]{4}", value):
            return date(int(value), 1, 1).year
        if re.fullmatch(r"[0-9]{4}-[0-9]{2}", value):
            return date(int(value[:4]), int(value[5:7]), 1).year
        if re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
            return date.fromisoformat(value).year
        if re.match(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}[T ]", value):
            return datetime.fromisoformat(value).year
    except ValueError:
        pass
    return None


def _positive_integer(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else None


def _duration(info: object) -> float | None:
    value: object = getattr(info, "length", None)
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return None
    duration = float(value)
    return duration if math.isfinite(duration) and duration >= 0 else None


def _image_info(data: bytes) -> tuple[str, int, int] | None:
    """Validate common image containers and dimensions without a GUI/image dependency."""
    if (
        len(data) >= 45
        and data.startswith(b"\x89PNG\r\n\x1a\n")
        and data[8:16] == b"\x00\x00\x00\rIHDR"
        and data[-12:-4] == b"\x00\x00\x00\x00IEND"
    ):
        width, height = struct.unpack(">II", data[16:24])
        return ("image/png", width, height) if width > 0 and height > 0 else None
    if len(data) >= 14 and data[:6] in (b"GIF87a", b"GIF89a") and data.endswith(b";"):
        width, height = struct.unpack("<HH", data[6:10])
        return ("image/gif", width, height) if width > 0 and height > 0 else None
    if not data.startswith(b"\xff\xd8") or b"\xff\xd9" not in data[2:]:
        return None
    offset = 2
    while offset + 4 <= len(data):
        if data[offset] != 0xFF:
            return None
        while offset < len(data) and data[offset] == 0xFF:
            offset += 1
        if offset >= len(data):
            return None
        marker = data[offset]
        offset += 1
        if marker in (0xD8, 0xD9) or 0xD0 <= marker <= 0xD7:
            continue
        if offset + 2 > len(data):
            return None
        length = int.from_bytes(data[offset : offset + 2], "big")
        if length < 2 or offset + length > len(data):
            return None
        if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
            if length < 8:
                return None
            height, width = struct.unpack(">HH", data[offset + 3 : offset + 7])
            return ("image/jpeg", width, height) if width > 0 and height > 0 else None
        offset += length
    return None


def _embedded_artwork(pictures: Iterable[tuple[int, bytes]]) -> Artwork | None:
    candidates = list(pictures)
    for _picture_type, data in sorted(candidates, key=lambda picture: picture[0] != 3):
        image = _image_info(data)
        if image is not None:
            mime_type, width, height = image
            return Artwork(data=data, mime_type=mime_type, width=width, height=height)
    return None


def _fallback_artwork(path: Path) -> Artwork | None:
    cover_path = path.parent / "album.jpg"
    try:
        data = cover_path.read_bytes()
    except OSError:
        return None
    image = _image_info(data)
    if image is None:
        return None
    mime_type, width, height = image
    return Artwork(
        data=data,
        mime_type=mime_type,
        width=width,
        height=height,
        source="album.jpg",
        source_path=cover_path.resolve(),
    )


def _id3_entries(tags: _Id3Tags | None) -> Iterable[tuple[str, str]]:
    if tags is None:
        return
    for key, frame in tags.items():
        text: object = getattr(frame, "text", getattr(frame, "url", None))
        if isinstance(text, str):
            yield key, text
        elif isinstance(text, (list, tuple)):
            for value in text:
                yield key, str(value)


def _id3_pictures(tags: _Id3Tags | None) -> Iterable[tuple[int, bytes]]:
    if tags is None:
        return
    for key, frame in tags.items():
        if key.split(":", 1)[0] != "APIC":
            continue
        data: object = getattr(frame, "data", None)
        picture_type: object = getattr(frame, "type", None)
        if isinstance(data, bytes) and isinstance(picture_type, int):
            yield picture_type, data


def _metadata(
    raw_tags: tuple[RawTagValue, ...], artwork: Artwork | None, info: object, audio_format: str
) -> TrackMetadata:
    track_number, track_total = _number_pair(
        _first(raw_tags, "tracknumber", "trck"),
        _first(raw_tags, "tracktotal", "totaltracks"),
    )
    disc_number, disc_total = _number_pair(
        _first(raw_tags, "discnumber", "tpos"),
        _first(raw_tags, "disctotal", "totaldiscs"),
    )
    album_date = _first(raw_tags, "date", "year", "tdrc", "tdrl", "tyer")
    return TrackMetadata(
        title=_first(raw_tags, "title", "tit2"),
        album=_first(raw_tags, "album", "talb"),
        album_year=_year(album_date),
        album_date=album_date,
        track_number=track_number,
        track_total=track_total,
        disc_number=disc_number,
        disc_total=disc_total,
        artists=_values(raw_tags, "artist", "tpe1"),
        album_artists=_values(raw_tags, "albumartist", "tpe2"),
        genres=_values(raw_tags, "genre", "tcon"),
        lyrics=_first(raw_tags, "lyrics", "unsyncedlyrics", "uslt"),
        artwork=artwork,
        raw_tags=raw_tags,
        audio_format=audio_format,
        duration_seconds=_duration(info),
        sample_rate_hz=_positive_integer(getattr(info, "sample_rate", None)),
        channels=_positive_integer(getattr(info, "channels", None)),
        bits_per_sample=_positive_integer(getattr(info, "bits_per_sample", None)),
    )


def read_metadata(path: Path) -> TrackMetadata:
    """Read detected FLAC/MP3 content; absent tags/artwork are valid results."""
    try:
        # Mutagen's public API is partly untyped; casts isolate it at this adapter boundary.
        read_audio = cast(Callable[..., object], mutagen.File)
        with path.open("rb") as source:
            # A neutral filename prevents extension scores overriding the actual header.
            audio = read_audio(source, options=[FLAC, MP3], filename="trackfolio-audio", easy=False)
        if isinstance(audio, FLAC):
            flac = cast(_FlacFile, audio)
            raw_tags = _raw_values(flac.tags or ())
            artwork = _embedded_artwork((picture.type, picture.data) for picture in flac.pictures)
            info, audio_format = flac.info, "flac"
        elif isinstance(audio, MP3):
            # Disable ID3 translation so original text frame keys/values are retained.
            try:
                id3 = cast(_Id3Tags, cast(Callable[..., object], ID3)(str(path), translate=False))
            except ID3NoHeaderError:
                id3 = None
            raw_tags = _raw_values(_id3_entries(id3))
            artwork = _embedded_artwork(_id3_pictures(id3))
            info, audio_format = cast(_Mp3File, audio).info, "mp3"
        else:
            raise UnsupportedAudioError(f"Formato no compatible con FLAC/MP3: {path}")
    except (OSError, mutagen.MutagenError, ValueError) as exc:
        raise MetadataReadError(f"No se pueden leer los metadatos de {path}: {exc}") from exc
    if artwork is None:
        artwork = _fallback_artwork(path)
    return _metadata(raw_tags, artwork, info, audio_format)
