"""Open existing read-only catalogs without creating or migrating files."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from sqlalchemy import URL, Engine, create_engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.pool import NullPool

from trackfolio.application.catalog import CatalogAccessError, CatalogSession
from trackfolio.domain.album import AlbumTrack
from trackfolio.domain.catalog import CatalogEntry, CatalogSummary
from trackfolio.infrastructure.album_catalog import read_album_tracks
from trackfolio.infrastructure.catalog import SqliteCatalogRepository
from trackfolio.infrastructure.database import _file_uri as _file_uri
from trackfolio.infrastructure.schema_validation import validate_catalog_connection


def _access_error(error: SQLAlchemyError, message: str) -> CatalogAccessError:
    original = getattr(error, "orig", None)
    code = getattr(original, "sqlite_errorcode", 0) & 0xFF
    if code in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED):
        return CatalogAccessError(
            "The catalog is busy in another application. Try again in a few seconds."
        )
    if code in (sqlite3.SQLITE_NOTADB, sqlite3.SQLITE_CORRUPT):
        return CatalogAccessError(
            "The file is not a valid SQLite database or is damaged. Select another catalog."
        )
    return CatalogAccessError(message)


def _validate_catalog(engine: Engine, *, require_current: bool = False) -> None:
    with engine.connect() as connection:
        validate_catalog_connection(connection, require_current=require_current)


class _SqliteCatalogSession:
    def __init__(self, path: Path, engine: Engine) -> None:
        self.database_path = path
        self._engine = engine
        self._repository = SqliteCatalogRepository(engine)
        self._closed = False

    def _check_open(self) -> None:
        if self._closed:
            raise RuntimeError("The catalog is closed.")

    def list_summaries(self) -> tuple[CatalogSummary, ...]:
        self._check_open()
        try:
            return self._repository.list_summaries()
        except SQLAlchemyError as exc:
            raise _access_error(
                exc,
                "Could not retrieve songs. Check the catalog and try again.",
            ) from exc

    def list_album_tracks(self) -> tuple[AlbumTrack, ...]:
        self._check_open()
        try:
            with self._engine.connect() as connection:
                return read_album_tracks(connection)
        except SQLAlchemyError as exc:
            raise _access_error(exc, "Could not retrieve albums.") from exc

    def get(self, file_id: int) -> CatalogEntry | None:
        self._check_open()
        try:
            return self._repository.get(file_id)
        except SQLAlchemyError as exc:
            raise _access_error(
                exc,
                "Could not read metadata. Check the catalog and try again.",
            ) from exc

    def close(self) -> None:
        if not self._closed:
            self._closed = True
            self._engine.dispose()


def open_catalog(path: Path | str) -> CatalogSession:
    """Open a recognized Trackfolio file with read-only connections.

    Each operation opens and closes its own connection. The caller must close
    the session when finished. Queries wait at most two seconds for SQLite
    locks; neither the schema nor the journal mode is changed.
    """
    database = Path(path).expanduser().resolve(strict=True)
    if not database.is_file():
        raise ValueError("Select an existing SQLite file.")
    engine = create_engine(
        URL.create(
            "sqlite",
            database=_file_uri(database),
            query={"mode": "ro", "uri": "true"},
        ),
        connect_args={"timeout": 2.0, "autocommit": False, "check_same_thread": False},
        poolclass=NullPool,
    )
    try:
        _validate_catalog(engine)
    except SQLAlchemyError as exc:
        engine.dispose()
        raise _access_error(
            exc, "Could not open the catalog. Check the file and try again."
        ) from exc
    except Exception:
        engine.dispose()
        raise
    return _SqliteCatalogSession(database, engine)
