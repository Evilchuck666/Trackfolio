"""Apertura de catálogos existentes de solo lectura, sin crear ni migrar archivos."""

from __future__ import annotations

import sqlite3
from pathlib import Path, PurePath
from urllib.parse import urlsplit

from sqlalchemy import URL, Engine, create_engine, inspect
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.pool import NullPool

from trackfolio.application.catalog import CatalogAccessError, CatalogSession
from trackfolio.domain.catalog import CatalogEntry, CatalogSummary
from trackfolio.infrastructure.catalog import SqliteCatalogRepository
from trackfolio.infrastructure.database import UnknownDatabaseError, metadata
from trackfolio.infrastructure.migrations.initial_schema import (
    APPLICATION_ID,
    REVISION,
    TRACK_DETAILS_SQL,
)


def _file_uri(path: PurePath) -> str:
    """Codificar nombres especiales y las rutas Windows, incluidas las UNC."""
    uri = path.as_uri()
    parsed = urlsplit(uri)
    if parsed.netloc:
        # SQLite no admite una autoridad remota con su compilación habitual.
        # Conservar la ruta UNC en la ruta del URI y dejar vacía su autoridad.
        uri = f"file:////{parsed.netloc}{parsed.path}"
    return uri


def _access_error(error: SQLAlchemyError, message: str) -> CatalogAccessError:
    original = getattr(error, "orig", None)
    code = getattr(original, "sqlite_errorcode", 0) & 0xFF
    if code in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED):
        return CatalogAccessError(
            "El catálogo está ocupado por otra aplicación. Vuelve a intentarlo en unos segundos."
        )
    if code in (sqlite3.SQLITE_NOTADB, sqlite3.SQLITE_CORRUPT):
        return CatalogAccessError(
            "El archivo no contiene una base SQLite válida o está dañado. Selecciona otro catálogo."
        )
    return CatalogAccessError(message)


def _validate_catalog(engine: Engine) -> None:
    with engine.connect() as connection:
        inspector = inspect(connection)
        if (
            connection.exec_driver_sql("PRAGMA application_id").scalar_one() != APPLICATION_ID
            or set(inspector.get_table_names()) != set(metadata.tables) | {"alembic_version"}
            or set(inspector.get_view_names()) != {"track_details"}
        ):
            raise UnknownDatabaseError("El archivo no contiene un catálogo Trackfolio compatible.")
        revisions: tuple[object, ...] = tuple(
            connection.exec_driver_sql("SELECT version_num FROM alembic_version").scalars()
        )
        if revisions != (REVISION,):
            raise UnknownDatabaseError("La revisión del catálogo Trackfolio no es compatible.")
        for table in metadata.sorted_tables:
            expected_columns = {column.name for column in table.columns}
            actual_columns = {
                column["name"]: column for column in inspector.get_columns(table.name)
            }
            if set(actual_columns) != expected_columns:
                raise UnknownDatabaseError("El esquema del catálogo Trackfolio no es compatible.")
            primary_key = inspector.get_pk_constraint(table.name)["constrained_columns"]
            if primary_key != [column.name for column in table.primary_key.columns]:
                raise UnknownDatabaseError("El esquema del catálogo Trackfolio no es compatible.")
            for column in table.columns:
                actual = actual_columns[column.name]
                if (
                    str(actual["type"]) != str(column.type.compile(dialect=engine.dialect))
                    or actual["nullable"] != column.nullable
                ):
                    raise UnknownDatabaseError(
                        "El esquema del catálogo Trackfolio no es compatible."
                    )
        view_sql = inspector.get_view_definition("track_details") or ""
        if " ".join(view_sql.split()) != " ".join(TRACK_DETAILS_SQL.split()):
            raise UnknownDatabaseError("La vista del catálogo Trackfolio no es compatible.")


class _SqliteCatalogSession:
    def __init__(self, path: Path, engine: Engine) -> None:
        self.database_path = path
        self._engine = engine
        self._repository = SqliteCatalogRepository(engine)
        self._closed = False

    def _check_open(self) -> None:
        if self._closed:
            raise RuntimeError("El catálogo está cerrado.")

    def list_summaries(self) -> tuple[CatalogSummary, ...]:
        self._check_open()
        try:
            return self._repository.list_summaries()
        except SQLAlchemyError as exc:
            raise _access_error(
                exc,
                "No se pudieron obtener las canciones. "
                "Comprueba el catálogo y vuelve a intentarlo.",
            ) from exc

    def get(self, file_id: int) -> CatalogEntry | None:
        self._check_open()
        try:
            return self._repository.get(file_id)
        except SQLAlchemyError as exc:
            raise _access_error(
                exc,
                "No se pudieron leer los metadatos. Comprueba el catálogo y vuelve a intentarlo.",
            ) from exc

    def close(self) -> None:
        if not self._closed:
            self._closed = True
            self._engine.dispose()


def open_catalog(path: Path | str) -> CatalogSession:
    """Abrir un archivo Trackfolio reconocido con conexiones de solo lectura.

    Cada operación abre y cierra su propia conexión. El llamante debe cerrar la
    sesión cuando deje de usarla. Las consultas esperan como máximo dos segundos
    ante un bloqueo de SQLite; no se altera el esquema ni el modo de diario.
    """
    database = Path(path).expanduser().resolve(strict=True)
    if not database.is_file():
        raise ValueError("Selecciona un archivo SQLite existente.")
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
            exc, "No se pudo abrir el catálogo. Comprueba el archivo y vuelve a intentarlo."
        ) from exc
    except Exception:
        engine.dispose()
        raise
    return _SqliteCatalogSession(database, engine)
