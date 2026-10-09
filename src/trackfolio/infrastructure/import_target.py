"""Destinos SQLite de importación con creación exclusiva y recursos acotados."""

from __future__ import annotations

import os
import sqlite3
import stat
from pathlib import Path

from alembic import command
from sqlalchemy import URL, Engine, create_engine, event
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.pool import NullPool

from trackfolio.application.catalog import CatalogAccessError
from trackfolio.application.import_catalog import (
    ImportIssue,
    ImportMode,
    ImportTargetError,
    SaveOutcome,
)
from trackfolio.domain.metadata import TrackMetadata
from trackfolio.infrastructure.catalog import SqliteCatalogRepository
from trackfolio.infrastructure.database import _enable_foreign_keys, migration_config
from trackfolio.infrastructure.session import _file_uri, _validate_catalog, open_catalog


def _writable_engine(path: Path) -> Engine:
    # mode=rw also protects every later connection if a file disappears. SQLite's
    # ordinary path mode would silently create an empty replacement database.
    engine = create_engine(
        URL.create("sqlite", database=_file_uri(path), query={"mode": "rw", "uri": "true"}),
        connect_args={"timeout": 2.0, "autocommit": False},
        poolclass=NullPool,
    )
    event.listen(engine, "connect", _enable_foreign_keys)
    return engine


def _target_error(error: Exception, message: str) -> ImportTargetError:
    original = getattr(error, "orig", error)
    code = getattr(original, "sqlite_errorcode", 0) & 0xFF
    if code in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED):
        return ImportTargetError(
            "El catálogo está ocupado por otra aplicación. Vuelve a intentarlo en unos segundos."
        )
    if code in (sqlite3.SQLITE_READONLY, sqlite3.SQLITE_PERM):
        return ImportTargetError("No hay permiso para escribir en el catálogo de destino.")
    if code in (sqlite3.SQLITE_NOTADB, sqlite3.SQLITE_CORRUPT):
        return ImportTargetError(
            "El catálogo de destino no es una base SQLite válida o está dañado."
        )
    if code == sqlite3.SQLITE_FULL:
        return ImportTargetError("No queda espacio para guardar el catálogo de destino.")
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
        raise ImportTargetError(f"No hay permiso para escribir en el destino: {path}")


def _check_parent(path: Path) -> None:
    parent = path.parent
    while not parent.exists() and not parent.is_symlink():
        parent = parent.parent
    if not parent.is_dir():
        raise ImportTargetError("El directorio del catálogo de destino no es válido.")
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
            raise ImportTargetError("El catálogo de destino está cerrado.")
        try:
            outcome = self._repository.write(metadata, library_root, relative_path)
        except (OSError, ValueError, RuntimeError, SQLAlchemyError) as exc:
            raise _target_error(
                exc, "No se pudo guardar el archivo en el catálogo de destino."
            ) from exc
        self._committed = True
        return outcome

    def close(self) -> None:
        if not self._closed:
            self._closed = True
            try:
                self._engine.dispose()
            except (OSError, SQLAlchemyError) as exc:
                raise _target_error(exc, "No se pudo cerrar el catálogo de destino.") from exc

    def discard(self) -> None:
        """Eliminar únicamente un catálogo propio sin escrituras confirmadas."""
        self.close()
        if self._owned_identity is None or self._committed:
            return
        try:
            if not self.database_path.exists() and not self.database_path.is_symlink():
                return
            if _identity(self.database_path) != self._owned_identity:
                raise ImportTargetError(
                    "El destino cambió durante la importación; no se ha eliminado el archivo."
                )
            self.database_path.unlink()
        except OSError as exc:
            raise ImportTargetError(
                f"No se pudo eliminar el catálogo nuevo sin canciones: {self.database_path}"
            ) from exc


class SqliteImportTargetFactory:
    def validate(self, database_path: Path, mode: ImportMode) -> Path:
        """Comprobar el formulario sin crear archivos, directorios ni migraciones."""
        try:
            if mode == "create":
                original = database_path.expanduser()
                database = original.parent.resolve() / original.name
                if database.exists() or database.is_symlink():
                    raise ImportTargetError(
                        "El catálogo de destino ya existe. Selecciona un archivo nuevo."
                    )
                _check_parent(database)
                return database
            if mode != "update":
                raise ImportTargetError("El modo de importación no es válido.")
            session = open_catalog(database_path)
            try:
                database = session.database_path
                _require_writable(database)
                _check_parent(database)
                return database
            finally:
                session.close()
        except (OSError, ValueError, CatalogAccessError, SQLAlchemyError) as exc:
            raise _target_error(exc, "No se pudo acceder al catálogo de destino.") from exc

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
            if mode == "create":
                with engine.begin() as connection:
                    config = migration_config()
                    config.attributes["connection"] = connection
                    command.upgrade(config, "head")
            _validate_catalog(engine)
            return SqliteImportTarget(database, engine, owned_identity)
        except Exception as exc:
            cleanup_issue = None
            if engine is not None:
                try:
                    engine.dispose()
                except (OSError, SQLAlchemyError) as close_error:
                    cleanup_issue = ImportIssue(
                        database, "cleanup", f"No se pudo cerrar el catálogo: {close_error}"
                    )
            if owned_identity is not None:
                try:
                    if _identity(database) == owned_identity:
                        database.unlink()
                    else:
                        raise OSError("El archivo de destino ya no pertenece a esta importación.")
                except FileNotFoundError:
                    pass
                except OSError as cleanup_error:
                    cleanup_issue = ImportIssue(
                        database,
                        "cleanup",
                        f"No se pudo eliminar el catálogo nuevo sin canciones: {cleanup_error}",
                    )
            error = _target_error(exc, "No se pudo preparar el catálogo de destino.")
            error.cleanup_issue = cleanup_issue
            raise error from exc
