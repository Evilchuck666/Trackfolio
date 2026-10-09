"""Preparar la base de datos e importar un archivo, sin modificar la música."""

from __future__ import annotations

import argparse
from pathlib import Path

from sqlalchemy.exc import SQLAlchemyError

from trackfolio.application.catalog import ImportAudio
from trackfolio.infrastructure.catalog import SqliteCatalogRepository
from trackfolio.infrastructure.database import create_engine, migrate_database
from trackfolio.infrastructure.metadata import MetadataReadError, read_metadata


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("audio", type=Path, help="Archivo FLAC o MP3 que se desea importar.")
    parser.add_argument(
        "--database",
        type=Path,
        default=Path("data/database.tfo"),
        help="Catálogo de destino (por defecto: %(default)s).",
    )
    parser.add_argument(
        "--library-root",
        type=Path,
        help="Raíz de la música; por defecto el directorio del archivo.",
    )
    args = parser.parse_args(argv)
    source = args.audio.expanduser().resolve()
    database = args.database.expanduser().resolve()
    engine = None
    try:
        # Leer antes de crear una BD: un archivo inválido no debe dejar una importación vacía.
        parsed = read_metadata(source)
        migrate_database(database)
        engine = create_engine(database)
        repository = SqliteCatalogRepository(engine)
        importer = ImportAudio(lambda _: parsed, repository)
        entry = importer.execute(source, args.library_root)
    except (OSError, ValueError, MetadataReadError, SQLAlchemyError) as exc:
        print(f"No se pudo importar: {exc}")
        return 1
    finally:
        if engine is not None:
            engine.dispose()
    print(f"Base de datos: {database}")
    print(
        f"Archivo importado: {entry.relative_path}; "
        f"file_id={entry.file_id}, track_id={entry.track_id}"
    )
    print("Consulta en SQLiteBrowser: SELECT * FROM track_details;")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
