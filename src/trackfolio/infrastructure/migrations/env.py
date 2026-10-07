"""Run the packaged migrations online or emit standalone transactional SQLite SQL."""

from pathlib import Path

from alembic import context
from sqlalchemy.engine import Connection, make_url

from trackfolio.infrastructure.database import _check_database, create_engine
from trackfolio.infrastructure.migrations.initial_schema import metadata

config = context.config


def run_offline() -> None:
    context.configure(
        url="sqlite://",
        target_metadata=metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        transactional_ddl=True,
    )
    context.execute("PRAGMA foreign_keys = ON")
    with context.begin_transaction():
        context.run_migrations()


def run_with_connection(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=metadata, transactional_ddl=True)
    with context.begin_transaction():
        context.run_migrations()


def run_online() -> None:
    connection = config.attributes.get("connection")
    if isinstance(connection, Connection):
        run_with_connection(connection)
        return
    url = make_url(config.get_main_option("sqlalchemy.url") or "sqlite:///data/trackfolio.sqlite3")
    if url.get_backend_name() != "sqlite" or not url.database or url.database == ":memory:":
        raise ValueError("Las migraciones necesitan una ruta de base de datos SQLite persistente.")
    database = Path(url.database)
    database.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(database)
    try:
        with engine.begin() as active:
            _check_database(active)
            run_with_connection(active)
    finally:
        engine.dispose()


if context.is_offline_mode():
    run_offline()
else:
    run_online()
