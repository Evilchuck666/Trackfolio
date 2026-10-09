"""Coordinación cancelable de una biblioteca musical, sin Qt ni persistencia concreta."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol

from trackfolio.application.catalog import (
    MetadataReader,
    MetadataReadError,
    prepare_audio_source,
    validate_library_root,
)
from trackfolio.domain.metadata import TrackMetadata

ImportMode = Literal["create", "update"]
ImportPhase = Literal["preparing", "scanning", "importing", "finalizing"]
ImportState = Literal["completed", "cancelled", "failed"]
IssueStage = Literal["scan", "read", "write", "cleanup"]


@dataclass(frozen=True, slots=True)
class ImportRequest:
    library_root: Path
    database_path: Path
    mode: ImportMode


@dataclass(frozen=True, slots=True)
class AudioSource:
    path: Path
    relative_path: str


@dataclass(frozen=True, slots=True)
class ImportIssue:
    path: Path
    stage: IssueStage
    message: str


@dataclass(frozen=True, slots=True)
class ScanResult:
    sources: tuple[AudioSource, ...]
    issues: tuple[ImportIssue, ...]
    completed: bool = True


@dataclass(frozen=True, slots=True)
class SaveOutcome:
    file_id: int
    track_id: int
    operation: Literal["created", "updated"]


@dataclass(frozen=True, slots=True)
class ImportProgress:
    phase: ImportPhase
    discovered: int
    total: int | None
    created: int
    updated: int
    failed: int
    current_path: Path | None = None

    @property
    def processed(self) -> int:
        return self.created + self.updated + self.failed

    @property
    def saved(self) -> int:
        return self.created + self.updated


@dataclass(frozen=True, slots=True)
class ImportReport:
    database_path: Path
    state: ImportState
    discovered: int
    total: int | None
    created: int
    updated: int
    failed: int
    issues: tuple[ImportIssue, ...]
    fatal_error: str | None = None

    @property
    def processed(self) -> int:
        return self.created + self.updated + self.failed

    @property
    def saved(self) -> int:
        return self.created + self.updated

    @property
    def pending(self) -> int | None:
        return None if self.total is None else self.total - self.processed


class AudioScanError(Exception):
    """La raíz musical no se puede explorar; un subdirectorio fallido es una incidencia."""


class ImportTargetError(Exception):
    """Fallo presentable del destino; puede incluir una limpieza fallida al abrirlo."""

    def __init__(self, message: str, cleanup_issue: ImportIssue | None = None) -> None:
        super().__init__(message)
        self.cleanup_issue = cleanup_issue


class AudioScanner(Protocol):
    def scan(
        self,
        root: Path,
        is_cancelled: Callable[[], bool],
        on_discovered: Callable[[int], None],
    ) -> ScanResult: ...


class CatalogWriter(Protocol):
    def write(
        self, metadata: TrackMetadata, library_root: Path, relative_path: str
    ) -> SaveOutcome: ...


class CatalogImportTarget(CatalogWriter, Protocol):
    def close(self) -> None: ...

    def discard(self) -> None: ...


class CatalogImportTargetFactory(Protocol):
    def validate(self, database_path: Path, mode: ImportMode) -> Path: ...

    def open(self, database_path: Path, mode: ImportMode) -> CatalogImportTarget: ...


class ImportCatalog:
    def __init__(
        self,
        scanner: AudioScanner,
        reader: MetadataReader,
        factory: CatalogImportTargetFactory,
    ) -> None:
        self.scanner = scanner
        self.reader = reader
        self.factory = factory

    def execute(
        self,
        request: ImportRequest,
        is_cancelled: Callable[[], bool] = lambda: False,
        on_progress: Callable[[ImportProgress], None] = lambda _: None,
    ) -> ImportReport:
        """Importa en transacciones individuales y devuelve siempre el avance confirmado."""
        database_path = request.database_path
        discovered = created = updated = failed = 0
        total: int | None = None
        issues: list[ImportIssue] = []
        state: ImportState = "completed"
        fatal_error: str | None = None
        target: CatalogImportTarget | None = None

        def progress(phase: ImportPhase, current_path: Path | None = None) -> None:
            on_progress(
                ImportProgress(phase, discovered, total, created, updated, failed, current_path)
            )

        def found(count: int) -> None:
            nonlocal discovered
            discovered = count
            progress("scanning")

        try:
            progress("preparing")
            if is_cancelled():
                state = "cancelled"
            else:
                root = validate_library_root(request.library_root)
                database_path = self.factory.validate(database_path, request.mode)
                if is_cancelled():
                    state = "cancelled"
                else:
                    progress("scanning")
                    scan = self.scanner.scan(root, is_cancelled, found)
                    issues.extend(scan.issues)
                    discovered = len(scan.sources)
                    if not scan.completed or is_cancelled():
                        state = "cancelled"
                    else:
                        total = discovered
                        progress("importing")
                        for source in scan.sources:
                            if is_cancelled():
                                state = "cancelled"
                                break
                            progress("importing", source.path)
                            try:
                                path, relative_path = prepare_audio_source(source.path, root)
                                if is_cancelled():
                                    state = "cancelled"
                                    break
                                metadata = self.reader(path)
                            except (OSError, ValueError, MetadataReadError) as exc:
                                failed += 1
                                issues.append(ImportIssue(source.path, "read", str(exc)))
                                progress("importing", source.path)
                                continue
                            if is_cancelled():
                                state = "cancelled"
                                break
                            if target is None:
                                target = self.factory.open(database_path, request.mode)
                            if is_cancelled():
                                state = "cancelled"
                                break
                            try:
                                outcome = target.write(metadata, root, relative_path)
                            except ImportTargetError as exc:
                                failed += 1
                                issues.append(ImportIssue(source.path, "write", str(exc)))
                                if exc.cleanup_issue is not None:
                                    issues.append(exc.cleanup_issue)
                                state = "failed"
                                fatal_error = str(exc)
                                progress("importing", source.path)
                                break
                            if outcome.operation == "created":
                                created += 1
                            else:
                                updated += 1
                            progress("importing", source.path)
        except (OSError, ValueError, MetadataReadError, AudioScanError, ImportTargetError) as exc:
            state = "failed"
            fatal_error = str(exc)
            if isinstance(exc, ImportTargetError) and exc.cleanup_issue is not None:
                issues.append(exc.cleanup_issue)
        finally:
            try:
                progress("finalizing")
            finally:
                if target is not None:
                    try:
                        target.close()
                    except (OSError, ImportTargetError) as exc:
                        issues.append(ImportIssue(database_path, "cleanup", str(exc)))
                        state = "failed"
                        fatal_error = fatal_error or str(exc)
                    if created + updated == 0:
                        try:
                            target.discard()
                        except (OSError, ImportTargetError) as exc:
                            issues.append(ImportIssue(database_path, "cleanup", str(exc)))
        return ImportReport(
            database_path,
            state,
            discovered,
            total,
            created,
            updated,
            failed,
            tuple(issues),
            fatal_error,
        )
