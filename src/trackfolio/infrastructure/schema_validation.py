"""Shared, read-only recognition of supported Trackfolio SQLite schemas."""

from sqlalchemy import inspect
from sqlalchemy.engine import Connection

from trackfolio.infrastructure.schema import (
    APPLICATION_ID,
    LEGACY_REVISION,
    REVISION,
    TRACK_DETAILS_SQL,
    metadata,
)


class UnknownDatabaseError(ValueError):
    """A database does not have a recognized Trackfolio schema."""


def _validate_artist_index(connection: Connection) -> None:
    indexes = {
        row["name"]: row
        for row in connection.exec_driver_sql("PRAGMA index_list('artists')").mappings()
    }
    expected = indexes.get("uq_artists_name")
    if expected is None or expected["unique"] != 1 or expected["partial"] != 0:
        raise UnknownDatabaseError("El catálogo no garantiza nombres únicos de artista.")
    keys = [
        row
        for row in connection.exec_driver_sql("PRAGMA index_xinfo('uq_artists_name')").mappings()
        if row["key"] == 1
    ]
    if len(keys) != 1 or keys[0]["name"] != "name" or keys[0]["coll"] != "BINARY":
        raise UnknownDatabaseError("El índice de nombres de artista no es compatible.")


def validate_catalog_connection(connection: Connection, *, require_current: bool = False) -> str:
    """Recognize 001/002 without migration; optionally require the writable schema."""
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
    if revisions not in ((LEGACY_REVISION,), (REVISION,)):
        raise UnknownDatabaseError("La revisión del catálogo Trackfolio no es compatible.")
    revision = str(revisions[0])
    if require_current and revision != REVISION:
        raise UnknownDatabaseError("El catálogo necesita actualizarse antes de escribir.")
    for table in metadata.sorted_tables:
        actual_columns = {column["name"]: column for column in inspector.get_columns(table.name)}
        if set(actual_columns) != {column.name for column in table.columns}:
            raise UnknownDatabaseError("El esquema del catálogo Trackfolio no es compatible.")
        primary_key = inspector.get_pk_constraint(table.name)["constrained_columns"]
        if primary_key != [column.name for column in table.primary_key.columns]:
            raise UnknownDatabaseError("El esquema del catálogo Trackfolio no es compatible.")
        for column in table.columns:
            actual = actual_columns[column.name]
            if (
                str(actual["type"]) != str(column.type.compile(dialect=connection.dialect))
                or actual["nullable"] != column.nullable
            ):
                raise UnknownDatabaseError("El esquema del catálogo Trackfolio no es compatible.")
    view_sql = inspector.get_view_definition("track_details") or ""
    if " ".join(view_sql.split()) != " ".join(TRACK_DETAILS_SQL.split()):
        raise UnknownDatabaseError("La vista del catálogo Trackfolio no es compatible.")
    if revision == REVISION:
        _validate_artist_index(connection)
    return revision
