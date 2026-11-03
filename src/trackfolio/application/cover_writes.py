"""Discover and resolve cover sources without involving a GUI or publishing files."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

from trackfolio.application.tag_write_errors import (
    TagWriteCancelled,
    TagWriteConflict,
    TagWriteError,
)
from trackfolio.domain.tag_write import (
    CoverCandidate,
    CoverChoice,
    CoverDiscovery,
    CoverFolder,
    CoverImage,
    TagCatalogSnapshot,
    TagWriteProgress,
)

if TYPE_CHECKING:
    from trackfolio.application.write_tags import TagCatalog, TagFiles


class CoverSources(Protocol):
    def scan(
        self, root: Path, folder: Path, cancelled: Callable[[], bool]
    ) -> tuple[CoverCandidate, ...]: ...

    def read(
        self, root: Path, candidate: CoverCandidate, cancelled: Callable[[], bool]
    ) -> CoverImage: ...

    def check(
        self, folder: CoverFolder, image: CoverImage | None, cancelled: Callable[[], bool]
    ) -> None: ...


class CoverSelectionRequired(TagWriteError):
    def __init__(self, discovery: CoverDiscovery) -> None:
        super().__init__("Elige una imagen para cada carpeta con varias portadas.")
        self.discovery = discovery


def discover_covers(
    catalog: TagCatalog,
    files: TagFiles,
    sources: CoverSources,
    database: Path,
    file_ids: tuple[int, ...],
    cancelled: Callable[[], bool],
    progress: Callable[[TagWriteProgress], None],
) -> CoverDiscovery:
    identity = files.identity(database)
    snapshots: list[TagCatalogSnapshot] = []
    groups: dict[tuple[Path, Path], list[int]] = {}
    for index, file_id in enumerate(file_ids):
        if cancelled():
            raise TagWriteCancelled("Exploración de portadas cancelada.")
        progress(TagWriteProgress("cover_discovery", index, len(file_ids)))
        snapshot = catalog.snapshot(database, file_id)
        snapshots.append(snapshot)
        folder = (snapshot.library_root.resolve() / snapshot.relative_path).parent
        groups.setdefault((snapshot.library_root.resolve(), folder), []).append(file_id)
    folders = []
    for (root, folder), ids in sorted(groups.items()):
        if cancelled():
            raise TagWriteCancelled("Exploración de portadas cancelada.")
        try:
            candidates = sources.scan(root, folder, cancelled)
            folders.append(CoverFolder(folder, root, tuple(ids), candidates))
        except TagWriteCancelled:
            raise
        except Exception as exc:
            folders.append(CoverFolder(folder, root, tuple(ids), error=str(exc)))
    if files.identity(database) != identity:
        raise TagWriteConflict("El catálogo cambió durante la exploración de portadas.")
    return CoverDiscovery(database, file_ids, identity, tuple(snapshots), tuple(folders))


def resolve_covers(
    discovery: CoverDiscovery,
    choices: tuple[CoverChoice, ...],
    sources: CoverSources,
    cancelled: Callable[[], bool],
) -> tuple[tuple[tuple[int, CoverImage], ...], tuple[int, ...], dict[int, str]]:
    if len({choice.folder for choice in choices}) != len(choices):
        raise TagWriteError("Hay elecciones de portada duplicadas.")
    selected = {choice.folder: choice.image for choice in choices}
    if any(path not in {folder.path for folder in discovery.folders} for path in selected):
        raise TagWriteError("La elección de portada no pertenece a la selección.")
    if any(
        len(folder.candidates) > 1 and folder.path not in selected for folder in discovery.folders
    ):
        raise CoverSelectionRequired(discovery)
    images: list[tuple[int, CoverImage]] = []
    skipped: list[int] = []
    errors: dict[int, str] = {}
    for folder in discovery.folders:
        if cancelled():
            raise TagWriteCancelled("Selección de portadas cancelada.")
        try:
            if folder.error:
                raise TagWriteError(folder.error)
            if folder.path in selected and selected[folder.path] is None:
                skipped.extend(folder.file_ids)
                continue
            candidate = None
            if folder.path in selected:
                candidate = next(
                    (c for c in folder.candidates if c.path == selected[folder.path]), None
                )
                if candidate is None:
                    raise TagWriteConflict("La imagen elegida ya no pertenece a esta carpeta.")
            elif len(folder.candidates) == 1:
                candidate = folder.candidates[0]
            sources.check(folder, None, cancelled)
            if candidate is not None:
                image = sources.read(folder.library_root, candidate, cancelled)
                images.extend((file_id, image) for file_id in folder.file_ids)
        except TagWriteCancelled:
            raise
        except Exception as exc:
            errors.update((file_id, str(exc)) for file_id in folder.file_ids)
    return tuple(images), tuple(skipped), errors
