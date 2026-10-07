"""Registros del catálogo independientes de la persistencia y de Qt."""

from dataclasses import dataclass
from pathlib import Path

from trackfolio.domain.metadata import TrackMetadata


@dataclass(frozen=True, slots=True)
class CatalogEntry:
    file_id: int
    track_id: int
    library_root: Path
    relative_path: str
    metadata: TrackMetadata


@dataclass(frozen=True, slots=True)
class CatalogSummary:
    """Datos ligeros de una canción para listas, sin portada ni líricas."""

    file_id: int
    track_id: int
    title: str | None
    artists: tuple[str, ...]
    album: str | None
    album_year: int | None
    relative_path: str
