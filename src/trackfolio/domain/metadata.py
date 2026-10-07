"""Immutable metadata values shared by every interface and storage adapter."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal


@dataclass(frozen=True, slots=True)
class RawTagValue:
    """One original text value; position is zero based within its original key."""

    key: str
    value: str
    position: int


@dataclass(frozen=True, slots=True)
class Artwork:
    data: bytes
    mime_type: str
    width: int | None = None
    height: int | None = None
    source: Literal["embedded", "album.jpg"] = "embedded"
    source_path: Path | None = None


@dataclass(frozen=True, slots=True)
class TrackMetadata:
    """Missing tags remain missing; display defaults belong to the interfaces."""

    title: str | None = None
    album: str | None = None
    album_year: int | None = None
    album_date: str | None = None
    track_number: int | None = None
    track_total: int | None = None
    disc_number: int | None = None
    disc_total: int | None = None
    artists: tuple[str, ...] = ()
    album_artists: tuple[str, ...] = ()
    genres: tuple[str, ...] = ()
    lyrics: str | None = None
    artwork: Artwork | None = None
    raw_tags: tuple[RawTagValue, ...] = ()
    audio_format: str | None = None
    duration_seconds: float | None = None
    sample_rate_hz: int | None = None
    channels: int | None = None
    bits_per_sample: int | None = None
