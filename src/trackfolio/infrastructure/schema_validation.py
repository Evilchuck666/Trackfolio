"""Shared, read-only recognition of supported Trackfolio SQLite schemas."""

from sqlalchemy import inspect
from sqlalchemy.engine import Connection

from trackfolio.infrastructure.schema import (
    APPLICATION_ID,
    COLUMNS_SINCE,
    LEGACY_REVISION,
    REVISION,
    SUPPORTED_REVISIONS,
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
        raise UnknownDatabaseError("The catalog does not guarantee unique artist names.")
    keys = [
        row
        for row in connection.exec_driver_sql("PRAGMA index_xinfo('uq_artists_name')").mappings()
        if row["key"] == 1
    ]
    if len(keys) != 1 or keys[0]["name"] != "name" or keys[0]["coll"] != "BINARY":
        raise UnknownDatabaseError("The artist name index is incompatible.")


def validate_catalog_connection(connection: Connection, *, require_current: bool = False) -> str:
    """Recognize every supported revision read-only; optionally require the writable one."""
    inspector = inspect(connection)
    if (
        connection.exec_driver_sql("PRAGMA application_id").scalar_one() != APPLICATION_ID
        or set(inspector.get_table_names()) != set(metadata.tables) | {"alembic_version"}
        or set(inspector.get_view_names()) != {"track_details"}
    ):
        raise UnknownDatabaseError("The file does not contain a compatible Trackfolio catalog.")
    revisions: tuple[object, ...] = tuple(
        connection.exec_driver_sql("SELECT version_num FROM alembic_version").scalars()
    )
    if len(revisions) != 1 or revisions[0] not in SUPPORTED_REVISIONS:
        raise UnknownDatabaseError("The Trackfolio catalog revision is incompatible.")
    revision = str(revisions[0])
    if require_current and revision != REVISION:
        raise UnknownDatabaseError("The catalog must be upgraded before writing.")
    order = SUPPORTED_REVISIONS.index(revision)
    for table in metadata.sorted_tables:
        actual_columns = {column["name"]: column for column in inspector.get_columns(table.name)}
        expected_columns = [
            column
            for column in table.columns
            if SUPPORTED_REVISIONS.index(
                COLUMNS_SINCE.get((table.name, column.name), LEGACY_REVISION)
            )
            <= order
        ]
        if set(actual_columns) != {column.name for column in expected_columns}:
            raise UnknownDatabaseError("The Trackfolio catalog schema is incompatible.")
        primary_key = inspector.get_pk_constraint(table.name)["constrained_columns"]
        if primary_key != [column.name for column in table.primary_key.columns]:
            raise UnknownDatabaseError("The Trackfolio catalog schema is incompatible.")
        for column in expected_columns:
            actual = actual_columns[column.name]
            if (
                str(actual["type"]) != str(column.type.compile(dialect=connection.dialect))
                or actual["nullable"] != column.nullable
            ):
                raise UnknownDatabaseError("The Trackfolio catalog schema is incompatible.")
    view_sql = inspector.get_view_definition("track_details") or ""
    if " ".join(view_sql.split()) != " ".join(TRACK_DETAILS_SQL.split()):
        raise UnknownDatabaseError("The Trackfolio catalog view is incompatible.")
    if revision != LEGACY_REVISION:
        _validate_artist_index(connection)
    return revision
