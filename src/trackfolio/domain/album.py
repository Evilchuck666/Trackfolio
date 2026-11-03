"""Album editions and their lightweight tracks, independent of Qt and storage."""

from dataclasses import dataclass
from pathlib import Path

from trackfolio.domain.catalog import CatalogSummary


@dataclass(frozen=True, slots=True)
class AlbumTrack:
    summary: CatalogSummary
    library_id: int
    library_root: Path
    album_artists: tuple[str, ...]
    album_date: str | None
    disc_number: int | None
    disc_total: int | None
    track_number: int | None
    duration_seconds: float | None
    genres: tuple[str, ...]
    has_cover: bool


@dataclass(frozen=True, slots=True)
class Album:
    key: str
    title: str | None
    year: int | None
    artists: tuple[str, ...]
    library_root: Path
    directory: str
    tracks: tuple[AlbumTrack, ...]

    @property
    def file_ids(self) -> tuple[int, ...]:
        return tuple(track.summary.file_id for track in self.tracks)

    @property
    def genres(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(genre for track in self.tracks for genre in track.genres))
