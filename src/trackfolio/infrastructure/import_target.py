"""SQLite import destinations with exclusive creation and bounded resources."""

from __future__ import annotations

import os
import sqlite3
import stat
from pathlib import Path

from sqlalchemy import Engine
from sqlalchemy.exc import SQLAlchemyError

from trackfolio.application.catalog import CatalogAccessError
from trackfolio.application.import_catalog import (
    ImportIssue,
    ImportMode,
    ImportTargetError,
    SaveOutcome,
)
from trackfolio.domain.metadata import TrackMetadata
from trackfolio.infrastructure.catalog import SqliteCatalogRepository
from trackfolio.infrastructure.database import migrate_engine
from trackfolio.infrastructure.database import writable_engine as _writable_engine
from trackfolio.infrastructure.session import _validate_catalog, open_catalog


def _target_error(error: Exception, message: str) -> ImportTargetError:
    original = getattr(error, "orig", error)
    code = getattr(original, "sqlite_errorcode", 0) & 0xFF
    if code in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED):
        return ImportTargetError(
            "The catalog is busy in another application. Try again in a few seconds."
        )
    if code in (sqlite3.SQLITE_READONLY, sqlite3.SQLITE_PERM):
        return ImportTargetError("Permission denied when writing to the destination catalog.")
    if code in (sqlite3.SQLITE_NOTADB, sqlite3.SQLITE_CORRUPT):
        return ImportTargetError(
            "The destination catalog is not a valid SQLite database or is damaged."
        )
    if code == sqlite3.SQLITE_FULL:
        return ImportTargetError("No space left to save the destination catalog.")
    if isinstance(error, (ValueError, CatalogAccessError, ImportTargetError)):
        return ImportTargetError(str(error))
    return ImportTargetError(message)


def _require_writable(path: Path, *, directory: bool = False) -> None:
    # The mode check makes a read-only target explicit even when an elevated Unix
    # account would bypass ordinary access checks. os.access also considers ACLs.
    permissions = path.stat().st_mode
    access_mode = os.W_OK | (os.X_OK if directory else 0)
    if permissions & (stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH) == 0 or not os.access(
        path, access_mode
    ):
        raise ImportTargetError(f"Permission denied when writing to the destination: {path}")


def _check_parent(path: Path) -> None:
    parent = path.parent
    while not parent.exists() and not parent.is_symlink():
        parent = parent.parent
    if not parent.is_dir():
        raise ImportTargetError("The destination catalog directory is invalid.")
    _require_writable(parent, directory=True)


def _identity(path: Path) -> tuple[int, int]:
    info = path.stat(follow_symlinks=False)
    return info.st_dev, info.st_ino


class SqliteImportTarget:
    def __init__(self, path: Path, engine: Engine, owned_identity: tuple[int, int] | None) -> None:
        self.database_path = path
        self._engine = engine
        self._repository = SqliteCatalogRepository(engine)
        self._owned_identity = owned_identity
        self._closed = False
        self._committed = False

    def write(self, metadata: TrackMetadata, library_root: Path, relative_path: str) -> SaveOutcome:
        if self._closed:
            raise ImportTargetError("The destination catalog is closed.")
        try:
            outcome = self._repository.write(metadata, library_root, relative_path)
        except (OSError, ValueError, RuntimeError, SQLAlchemyError) as exc:
            raise _target_error(exc, "Could not save the file to the destination catalog.") from exc
        self._committed = True
        return outcome

    def close(self) -> None:
        if not self._closed:
            self._closed = True
            try:
                self._engine.dispose()
            except (OSError, SQLAlchemyError) as exc:
                raise _target_error(exc, "Could not close the destination catalog.") from exc

    def discard(self) -> None:
        """Remove only a catalog we own that has no confirmed writes."""
        self.close()
        if self._owned_identity is None or self._committed:
            return
        try:
            if not self.database_path.exists() and not self.database_path.is_symlink():
                return
            if _identity(self.database_path) != self._owned_identity:
                raise ImportTargetError(
                    "The destination changed during import; the file has not been removed."
                )
            self.database_path.unlink()
        except OSError as exc:
            raise ImportTargetError(
                f"Could not remove the new catalog without songs: {self.database_path}"
            ) from exc


class SqliteImportTargetFactory:
    def validate(self, database_path: Path, mode: ImportMode) -> Path:
        """Check the form without creating files, directories or migrations."""
        try:
            if mode == "create":
                original = database_path.expanduser()
                database = original.parent.resolve() / original.name
                if database.exists() or database.is_symlink():
                    raise ImportTargetError(
                        "The destination catalog already exists. Select a new file."
                    )
                _check_parent(database)
                return database
            if mode != "update":
                raise ImportTargetError("The import mode is invalid.")
            session = open_catalog(database_path)
            try:
                database = session.database_path
                _require_writable(database)
                _check_parent(database)
                return database
            finally:
                session.close()
        except (OSError, ValueError, CatalogAccessError, SQLAlchemyError) as exc:
            raise _target_error(exc, "Could not access the destination catalog.") from exc

    def open(self, database_path: Path, mode: ImportMode) -> SqliteImportTarget:
        engine: Engine | None = None
        owned_identity: tuple[int, int] | None = None
        database = database_path
        try:
            database = self.validate(database_path, mode)
            if mode == "create":
                database.parent.mkdir(parents=True, exist_ok=True)
                # Preserve ownership across validation/open races and reject even
                # dangling links at the filename. Never adopt a file created by others.
                descriptor = os.open(database, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
                try:
                    info = os.fstat(descriptor)
                    owned_identity = info.st_dev, info.st_ino
                finally:
                    os.close(descriptor)
            engine = _writable_engine(database)
            migrate_engine(engine, database, require_catalog=mode == "update")
            _validate_catalog(engine, require_current=True)
            return SqliteImportTarget(database, engine, owned_identity)
        except Exception as exc:
            cleanup_issue = None
            if engine is not None:
                try:
                    engine.dispose()
                except (OSError, SQLAlchemyError) as close_error:
                    cleanup_issue = ImportIssue(
                        database, "cleanup", f"Could not close the catalog: {close_error}"
                    )
            if owned_identity is not None:
                try:
                    if _identity(database) == owned_identity:
                        database.unlink()
                    else:
                        raise OSError("The destination file no longer belongs to this import.")
                except FileNotFoundError:
                    pass
                except OSError as cleanup_error:
                    cleanup_issue = ImportIssue(
                        database,
                        "cleanup",
                        f"Could not remove the new catalog without songs: {cleanup_error}",
                    )
            error = _target_error(exc, "Could not prepare the destination catalog.")
            error.cleanup_issue = cleanup_issue
            raise error from exc
