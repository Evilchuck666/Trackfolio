"""Importación y consulta del catálogo mediante contratos, sin GUI ni ORM."""

from pathlib import Path
from typing import Protocol

from trackfolio.domain.catalog import CatalogEntry, CatalogSummary
from trackfolio.domain.metadata import TrackMetadata


class CatalogAccessError(Exception):
    """Un catálogo no está accesible; el mensaje puede presentarse en cualquier interfaz."""


class MetadataReadError(Exception):
    """El archivo de audio no se puede leer; el mensaje es apto para la interfaz."""


class UnsupportedAudioError(MetadataReadError):
    """El contenido detectado no es uno de los formatos FLAC/MP3 admitidos."""


def validate_library_root(root: Path) -> Path:
    """Normaliza una raíz existente antes de leer audio o preparar el destino."""
    root = root.expanduser().resolve(strict=True)
    if not root.is_dir():
        raise ValueError("La raíz de la biblioteca debe ser un directorio.")
    return root


def prepare_audio_source(source: Path, root: Path) -> tuple[Path, str]:
    """Valida de nuevo un candidato, también si el árbol cambió tras explorarlo."""
    original = source.expanduser().absolute()
    resolved = original.resolve(strict=True)
    try:
        relative_path = resolved.relative_to(root).as_posix()
    except ValueError as exc:
        raise ValueError("El archivo debe estar dentro de la raíz de la biblioteca.") from exc
    if not resolved.is_file():
        raise ValueError("El archivo de audio debe ser un archivo regular.")
    # Exclude links/junctions below the selected root, including a directory replaced
    # after scanning. An explicitly selected root can itself be a normalized alias.
    candidate = original
    while candidate.resolve(strict=True) != root:
        if candidate.is_symlink() or candidate.is_junction():
            raise ValueError("No se importan enlaces simbólicos ni puntos de unión.")
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
    """Catálogo abierto para lectura; la interfaz no conoce su motor de BD."""

    database_path: Path

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
