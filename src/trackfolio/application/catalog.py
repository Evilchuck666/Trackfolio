"""Importación y consulta del catálogo mediante contratos, sin GUI ni ORM."""

from pathlib import Path
from typing import Protocol

from trackfolio.domain.catalog import CatalogEntry
from trackfolio.domain.metadata import TrackMetadata


class MetadataReader(Protocol):
    def __call__(self, path: Path) -> TrackMetadata: ...


class CatalogRepository(Protocol):
    def save(
        self, metadata: TrackMetadata, library_root: Path, relative_path: str
    ) -> CatalogEntry: ...

    def get(self, file_id: int) -> CatalogEntry | None: ...

    def list_entries(self) -> tuple[CatalogEntry, ...]: ...


class ImportAudio:
    def __init__(self, reader: MetadataReader, repository: CatalogRepository) -> None:
        self.reader = reader
        self.repository = repository

    def execute(self, source: Path, library_root: Path | None = None) -> CatalogEntry:
        source = source.expanduser().resolve(strict=True)
        root = (library_root or source.parent).expanduser().resolve(strict=True)
        if not root.is_dir():
            raise ValueError("La raíz de la biblioteca debe ser un directorio.")
        try:
            relative_path = source.relative_to(root).as_posix()
        except ValueError as exc:
            raise ValueError("El archivo debe estar dentro de la raíz de la biblioteca.") from exc
        metadata = self.reader(source)
        return self.repository.save(metadata, root, relative_path)


class GetTrack:
    def __init__(self, repository: CatalogRepository) -> None:
        self.repository = repository

    def execute(self, file_id: int) -> CatalogEntry | None:
        return self.repository.get(file_id)


class ListTracks:
    def __init__(self, repository: CatalogRepository) -> None:
        self.repository = repository

    def execute(self) -> tuple[CatalogEntry, ...]:
        return self.repository.list_entries()
