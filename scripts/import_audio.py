"""Set up the database and import a file without modifying the music."""

from __future__ import annotations

import argparse
from pathlib import Path

from sqlalchemy.exc import SQLAlchemyError

from trackfolio.application.catalog import (
    ImportAudio,
    prepare_audio_source,
    validate_library_root,
)
from trackfolio.infrastructure.catalog import SqliteCatalogRepository
from trackfolio.infrastructure.database import create_engine, migrate_database
from trackfolio.infrastructure.metadata import MetadataReadError, read_metadata


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("audio", type=Path, help="FLAC or MP3 file to import.")
    parser.add_argument(
        "--database",
        type=Path,
        default=Path("data/database.tfo"),
        help="Destination catalog (default: %(default)s).",
    )
    parser.add_argument(
        "--library-root",
        type=Path,
        help="Music root; defaults to the file's directory.",
    )
    args = parser.parse_args(argv)
    source = args.audio.expanduser().absolute()
    database = args.database.expanduser().resolve()
    engine = None
    try:
        root = validate_library_root(args.library_root or source.parent)
        source, _ = prepare_audio_source(source, root)
        # Read before creating a database: an invalid file must not leave an empty import.
        parsed = read_metadata(source)
        migrate_database(database)
        engine = create_engine(database)
        repository = SqliteCatalogRepository(engine)
        importer = ImportAudio(lambda _: parsed, repository)
        entry = importer.execute(source, root)
    except (OSError, ValueError, MetadataReadError, SQLAlchemyError) as exc:
        print(f"Could not import: {exc}")
        return 1
    finally:
        if engine is not None:
            engine.dispose()
    print(f"Database: {database}")
    print(
        f"Imported file: {entry.relative_path}; file_id={entry.file_id}, track_id={entry.track_id}"
    )
    print("Query in SQLiteBrowser: SELECT * FROM track_details;")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
