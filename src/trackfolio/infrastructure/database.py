"""SQLite engine, guarded migrations and the current SQLAlchemy Core tables."""

from __future__ import annotations

import argparse
import io
import os
import sqlite3
import time
import uuid
from contextlib import closing
from pathlib import Path, PurePath
from typing import TextIO
from urllib.parse import urlsplit

from alembic import command
from alembic.config import Config
from sqlalchemy import URL, event, inspect
from sqlalchemy import create_engine as sqlalchemy_create_engine
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.pool import NullPool

from trackfolio.infrastructure.schema import (
    APPLICATION_ID,
    LEGACY_REVISION,
    REVISION,
    album_artists,
    albums,
    artists,
    artworks,
    audio_files,
    genres,
    libraries,
    metadata,
    raw_tags,
    track_artists,
    track_genres,
    tracks,
)
from trackfolio.infrastructure.schema_validation import (
    UnknownDatabaseError,
    validate_catalog_connection,
)

__all__ = [
    "UnknownDatabaseError",
    "album_artists",
    "albums",
    "artists",
    "artworks",
    "audio_files",
    "create_engine",
    "current_schema_sql",
    "genres",
    "initial_schema_sql",
    "libraries",
    "metadata",
    "migrate_database",
    "migrate_engine",
    "migration_config",
    "raw_tags",
    "track_artists",
    "track_genres",
    "tracks",
    "upgrade_database",
]


def _enable_foreign_keys(connection: sqlite3.Connection, _: object) -> None:
    previous = connection.autocommit
    connection.autocommit = True
    try:
        connection.execute("PRAGMA foreign_keys = ON")
    finally:
        connection.autocommit = previous


def create_engine(path: Path | str) -> Engine:
    """Create a path-safe SQLite engine with FK checks and transactional DDL.

    The caller owns engine.dispose(). This function does not create directories,
    migrate a database or change journal modes.
    """
    engine = sqlalchemy_create_engine(
        URL.create("sqlite", database=str(Path(path))),
        connect_args={"autocommit": False},
    )
    event.listen(engine, "connect", _enable_foreign_keys)
    return engine


def _file_uri(path: PurePath) -> str:
    """Encode portable SQLite file URIs, including Windows UNC paths."""
    uri = path.as_uri()
    parsed = urlsplit(uri)
    if parsed.netloc:
        uri = f"file:////{parsed.netloc}{parsed.path}"
    return uri


def writable_engine(path: Path) -> Engine:
    """Open an existing file without ever creating a replacement."""
    engine = sqlalchemy_create_engine(
        URL.create("sqlite", database=_file_uri(path), query={"mode": "rw", "uri": "true"}),
        connect_args={"timeout": 2.0, "autocommit": False},
        poolclass=NullPool,
    )
    event.listen(engine, "connect", _enable_foreign_keys)
    return engine


def migration_config(output_buffer: TextIO | None = None) -> Config:
    """Build Alembic configuration from package resources without a checkout."""
    config = Config(output_buffer=output_buffer)
    config.set_main_option("script_location", "trackfolio.infrastructure:migrations")
    return config


def _check_database(connection: Connection) -> str | None:
    inspector = inspect(connection)
    tables = set(inspector.get_table_names())
    views = set(inspector.get_view_names())
    application_id: object = connection.exec_driver_sql("PRAGMA application_id").scalar_one()
    if not tables and not views and application_id == 0:
        return None
    if (
        tables == {"alembic_version"}
        and not views
        and application_id == APPLICATION_ID
        and connection.exec_driver_sql("SELECT version_num FROM alembic_version").first() is None
    ):
        return None  # A recognized catalog explicitly downgraded to base.
    try:
        return validate_catalog_connection(connection)
    except UnknownDatabaseError as exc:
        raise UnknownDatabaseError(
            "La base de datos no está vacía y no tiene un esquema Trackfolio reconocido. "
            "Selecciona una base nueva; no se adoptan ni sobrescriben bases desconocidas."
        ) from exc


def _backup_database(database: Path) -> Path:
    """Copy a coherent SQLite snapshot to an exclusively reserved sibling file."""
    backup = database.with_name(f"{database.name}.{LEGACY_REVISION}.{uuid.uuid4().hex}.bak")
    descriptor = os.open(backup, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        identity = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    started = time.monotonic()

    def check_busy(status: int, _remaining: int, _total: int) -> None:
        if status in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED) and (
            time.monotonic() - started >= 2.0
        ):
            raise TimeoutError("El catálogo está ocupado; no se pudo crear su respaldo.")

    try:
        with (
            closing(
                sqlite3.connect(
                    f"{_file_uri(database)}?mode=ro", uri=True, timeout=2.0, autocommit=True
                )
            ) as source,
            closing(sqlite3.connect(backup, timeout=2.0, autocommit=True)) as destination,
        ):
            source.backup(destination, pages=128, progress=check_busy, sleep=0.05)
    except BaseException:
        info = backup.stat(follow_symlinks=False)
        if (info.st_dev, info.st_ino) == (identity.st_dev, identity.st_ino):
            backup.unlink()
        raise
    return backup


def prepare_migration_connection(
    connection: Connection, database: Path, *, require_catalog: bool = False
) -> tuple[str | None, Path | None]:
    """Validate, reserve the writer and back up an old catalog before any DDL.

    Python's autocommit=False starts a deferred SQLite transaction. Restart it
    as IMMEDIATE so other writers cannot change the catalog between its backup
    and migration. The backup reads through a separate connection; backing up
    the connection holding the writer lock would wait for itself.
    """
    revision = _check_database(connection)
    if require_catalog and revision is None:
        raise UnknownDatabaseError("El archivo no contiene un catálogo Trackfolio compatible.")
    if revision == REVISION:
        return revision, None
    connection.exec_driver_sql("ROLLBACK")
    connection.exec_driver_sql("BEGIN IMMEDIATE")
    revision = _check_database(connection)
    if require_catalog and revision is None:
        raise UnknownDatabaseError("El archivo no contiene un catálogo Trackfolio compatible.")
    backup = _backup_database(database) if revision == LEGACY_REVISION else None
    return revision, backup


def migrate_engine(engine: Engine, database: Path, *, require_catalog: bool = False) -> Path | None:
    """Upgrade using an owned engine and return the legacy backup, when needed."""
    with engine.begin() as connection:
        revision, backup = prepare_migration_connection(
            connection, database, require_catalog=require_catalog
        )
        if revision != REVISION:
            config = migration_config()
            config.attributes["connection"] = connection
            command.upgrade(config, "head")
        validate_catalog_connection(connection, require_current=True)
    return backup


def _migration_engine(path: Path | str, *, require_existing: bool = False) -> tuple[Path, Engine]:
    original = Path(path).expanduser()
    if require_existing or original.exists() or original.is_symlink():
        database = original.resolve(strict=True)
        if not database.is_file():
            raise ValueError("Selecciona un archivo SQLite existente.")
        return database, writable_engine(database)
    database = original.resolve()
    database.parent.mkdir(parents=True, exist_ok=True)
    return database, create_engine(database)


def migrate_database(path: Path | str) -> Path | None:
    """Create/upgrade a recognized database atomically, backing up revision 001."""
    database, engine = _migration_engine(path)
    try:
        return migrate_engine(engine, database)
    finally:
        engine.dispose()


def upgrade_database(path: Path | str) -> Path | None:
    """Upgrade an existing catalog without importing music or creating files."""
    database, engine = _migration_engine(path, require_existing=True)
    try:
        return migrate_engine(engine, database, require_catalog=True)
    finally:
        engine.dispose()


def initial_schema_sql() -> str:
    """Generate the standalone initial SQL artifact from the canonical revision."""
    output = io.StringIO()
    output.write(
        "-- Generated by Trackfolio's packaged Alembic revision 001_initial.\n"
        "-- Execute only against a new, empty SQLite database.\n"
        "-- Regenerate: uv run --locked python -m trackfolio.infrastructure.database "
        "--export-sql migrations/001_initial.sql\n\n"
    )
    command.upgrade(migration_config(output), LEGACY_REVISION, sql=True)
    return output.getvalue()


def current_schema_sql() -> str:
    """Generate standalone creation SQL through the current Alembic revision."""
    output = io.StringIO()
    output.write(
        f"-- Generated by Trackfolio's packaged Alembic revision {REVISION}.\n"
        "-- Execute only against a new, empty SQLite database.\n"
        "-- Regenerate: uv run --locked python -m trackfolio.infrastructure.database "
        "--export-current-sql migrations/002_current.sql\n\n"
    )
    command.upgrade(migration_config(output), REVISION, sql=True)
    return output.getvalue()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Exportar SQL o actualizar un catálogo Trackfolio."
    )
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--export-sql", type=Path, help="Exportar el esquema histórico 001.")
    action.add_argument("--export-current-sql", type=Path, help="Exportar el esquema vigente.")
    action.add_argument(
        "--upgrade", type=Path, help="Respaldar y actualizar un catálogo existente."
    )
    args = parser.parse_args()
    if args.upgrade is not None:
        try:
            backup = upgrade_database(args.upgrade)
        except (OSError, ValueError, sqlite3.Error, SQLAlchemyError) as exc:
            parser.exit(1, f"No se pudo actualizar el catálogo: {exc}\n")
        print(f"Catálogo actualizado a {REVISION}: {args.upgrade}")
        if backup is not None:
            print(f"Respaldo anterior: {backup}")
        return
    target = args.export_sql if args.export_sql is not None else args.export_current_sql
    sql = initial_schema_sql() if args.export_sql is not None else current_schema_sql()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(sql, encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()
