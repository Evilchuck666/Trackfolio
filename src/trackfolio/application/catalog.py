"""Catalog import and queries through contracts, without a GUI or ORM."""

from pathlib import Path
from typing import Protocol

from trackfolio.domain.album import AlbumTrack
from trackfolio.domain.catalog import CatalogEntry, CatalogSummary
from trackfolio.domain.metadata import TrackMetadata

AUDIO_SUFFIXES = (".flac", ".mp3")


class CatalogAccessError(Exception):
    """A catalog is inaccessible; the message can be shown in any interface."""


class MetadataReadError(Exception):
    """The audio file cannot be read; the message is suitable for the interface."""


class UnsupportedAudioError(MetadataReadError):
    """The detected content is not a supported FLAC/MP3 format."""


def validate_library_root(root: Path) -> Path:
    """Normalize an existing root before reading audio or preparing the destination."""
    root = root.expanduser().resolve(strict=True)
    if not root.is_dir():
        raise ValueError("The library root must be a directory.")
    return root


def prepare_audio_source(source: Path, root: Path) -> tuple[Path, str]:
    """Revalidate a candidate, including when the tree changed after scanning."""
    original = source.expanduser().absolute()
    resolved = original.resolve(strict=True)
    try:
        relative_path = resolved.relative_to(root).as_posix()
    except ValueError as exc:
        raise ValueError("The file must be inside the library root.") from exc
    if not resolved.is_file():
        raise ValueError("The audio file must be a regular file.")
    # Exclude links/junctions below the selected root, including a directory replaced
    # after scanning. An explicitly selected root can itself be a normalized alias.
    candidate = original
    while candidate.resolve(strict=True) != root:
        if candidate.is_symlink() or candidate.is_junction():
            raise ValueError("Symbolic links and junctions are not imported.")
        parent = candidate.parent
        if parent == candidate:
            break
        candidate = parent
    return resolved, relative_path


class MetadataReader(Protocol):
    def __call__(self, path: Path) -> TrackMetadata: ...


class TrackLookup(Protocol):
    def get(self, file_id: int) -> CatalogEntry | None: ...


class SummaryListing(Protocol):
    def list_summaries(self) -> tuple[CatalogSummary, ...]: ...


class CatalogRepository(TrackLookup, SummaryListing, Protocol):
    def save(
        self, metadata: TrackMetadata, library_root: Path, relative_path: str
    ) -> CatalogEntry: ...

    def list_entries(self) -> tuple[CatalogEntry, ...]: ...


class CatalogSession(TrackLookup, SummaryListing, Protocol):
    """Catalog opened for reading; the interface does not know its database engine."""

    database_path: Path

    def list_album_tracks(self) -> tuple[AlbumTrack, ...]: ...

    def close(self) -> None: ...


class ImportAudio:
    def __init__(self, reader: MetadataReader, repository: CatalogRepository) -> None:
        self.reader = reader
        self.repository = repository

    def execute(self, source: Path, library_root: Path | None = None) -> CatalogEntry:
        root = validate_library_root(library_root or source.expanduser().parent)
        source, relative_path = prepare_audio_source(source, root)
        metadata = self.reader(source)
        return self.repository.save(metadata, root, relative_path)


class GetTrack:
    def __init__(self, repository: TrackLookup) -> None:
        self.repository = repository

    def execute(self, file_id: int) -> CatalogEntry | None:
        return self.repository.get(file_id)


class ListTracks:
    def __init__(self, repository: CatalogRepository) -> None:
        self.repository = repository

    def execute(self) -> tuple[CatalogEntry, ...]:
        return self.repository.list_entries()


class ListTrackSummaries:
    def __init__(self, repository: SummaryListing) -> None:
        self.repository = repository

    def execute(self) -> tuple[CatalogSummary, ...]:
        return self.repository.list_summaries()
