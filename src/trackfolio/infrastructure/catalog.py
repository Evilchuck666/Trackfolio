"""Repositorio SQLAlchemy del catálogo; los contratos públicos usan dataclasses."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath
from typing import Any

from sqlalchemy import Connection, Engine, Table, delete, insert, select, update

from trackfolio.application.import_catalog import SaveOutcome
from trackfolio.domain.catalog import CatalogEntry, CatalogSummary
from trackfolio.domain.metadata import Artwork, RawTagValue, TrackMetadata
from trackfolio.infrastructure.database import (
    album_artists,
    albums,
    artists,
    artworks,
    audio_files,
    genres,
    libraries,
    raw_tags,
    track_artists,
    track_genres,
    tracks,
)


def _insert_id(connection: Connection, table: Table, values: dict[str, Any]) -> int:
    result = connection.execute(insert(table).values(**values))
    primary_key = result.inserted_primary_key
    if primary_key is None or primary_key[0] is None:
        raise RuntimeError("La inserción no devolvió una clave primaria.")
    return int(primary_key[0])


def _unique_labels(values: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(value for value in values if value.strip()))


class SqliteCatalogRepository:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def _album_id(
        self, connection: Connection, metadata: TrackMetadata, library_id: int, directory: str
    ) -> int | None:
        if (
            metadata.album is None
            and metadata.album_date is None
            and metadata.album_year is None
            and not metadata.album_artists
            and metadata.disc_total is None
        ):
            return None
        context = {
            "library_id": library_id,
            "directory": directory,
            "title": metadata.album,
            "date": metadata.album_date,
            "year": metadata.album_year,
            "disc_total": metadata.disc_total,
            "album_artists": metadata.album_artists,
        }
        import_key = hashlib.sha256(
            json.dumps(context, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()
        existing = connection.execute(
            select(albums.c.id).where(albums.c.import_key == import_key)
        ).scalar_one_or_none()
        if existing is not None:
            return int(existing)
        return _insert_id(
            connection,
            albums,
            {
                "library_id": library_id,
                "directory": directory,
                "import_key": import_key,
                "title": metadata.album,
                "year": metadata.album_year,
                "date": metadata.album_date,
                "disc_total": metadata.disc_total,
            },
        )

    def _artist_id(
        self,
        connection: Connection,
        name: str,
        album_id: int | None,
        library_id: int,
        directory: str,
    ) -> int:
        if album_id is not None:
            existing = connection.execute(
                select(artists.c.id)
                .join(album_artists, album_artists.c.artist_id == artists.c.id)
                .where(album_artists.c.album_id == album_id, artists.c.name == name)
                .order_by(artists.c.id)
                .limit(1)
            ).scalar_one_or_none()
            if existing is not None:
                return int(existing)
            existing = connection.execute(
                select(artists.c.id)
                .join(track_artists, track_artists.c.artist_id == artists.c.id)
                .join(tracks, tracks.c.id == track_artists.c.track_id)
                .where(tracks.c.album_id == album_id, artists.c.name == name)
                .order_by(artists.c.id)
                .limit(1)
            ).scalar_one_or_none()
            if existing is not None:
                return int(existing)
        else:
            candidates = connection.execute(
                select(artists.c.id, audio_files.c.relative_path)
                .join(track_artists, track_artists.c.artist_id == artists.c.id)
                .join(audio_files, audio_files.c.track_id == track_artists.c.track_id)
                .join(tracks, tracks.c.id == audio_files.c.track_id)
                .where(
                    audio_files.c.library_id == library_id,
                    tracks.c.album_id.is_(None),
                    artists.c.name == name,
                )
                .order_by(artists.c.id)
            )
            for candidate in candidates:
                if PurePosixPath(str(candidate.relative_path)).parent.as_posix() == directory:
                    return int(candidate.id)
        return _insert_id(connection, artists, {"name": name})

    def save(self, metadata: TrackMetadata, library_root: Path, relative_path: str) -> CatalogEntry:
        outcome = self.write(metadata, library_root, relative_path)
        entry = self.get(outcome.file_id)
        if entry is None:
            raise RuntimeError("La importación no produjo un registro consultable.")
        return entry

    def write(self, metadata: TrackMetadata, library_root: Path, relative_path: str) -> SaveOutcome:
        """Guardar una transacción y devolver sus identificadores, sin releer el detalle."""
        relative = PurePosixPath(relative_path)
        if relative.is_absolute() or ".." in relative.parts or not relative.parts:
            raise ValueError("La ruta del archivo debe ser relativa a la biblioteca.")
        directory = relative.parent.as_posix()
        with self.engine.begin() as connection:
            root_path = library_root.as_posix()
            existing_library = connection.execute(
                select(libraries.c.id).where(libraries.c.root_path == root_path)
            ).scalar_one_or_none()
            library_id = (
                int(existing_library)
                if existing_library is not None
                else _insert_id(connection, libraries, {"root_path": root_path})
            )
            album_id = self._album_id(connection, metadata, library_id, directory)
            existing_file = connection.execute(
                select(audio_files.c.id, audio_files.c.track_id).where(
                    audio_files.c.library_id == library_id,
                    audio_files.c.relative_path == relative.as_posix(),
                )
            ).one_or_none()
            track_values: dict[str, Any] = {
                "album_id": album_id,
                "title": metadata.title,
                "track_number": metadata.track_number,
                "track_total": metadata.track_total,
                "disc_number": metadata.disc_number,
                "disc_total": metadata.disc_total,
                "lyrics": metadata.lyrics,
            }
            if existing_file is None:
                track_id = _insert_id(connection, tracks, track_values)
            else:
                track_id = int(existing_file.track_id)
                connection.execute(
                    update(tracks).where(tracks.c.id == track_id).values(**track_values)
                )

            artist_cache: dict[str, int] = {}

            def artist_id_for(name: str) -> int:
                if name not in artist_cache:
                    artist_cache[name] = self._artist_id(
                        connection, name, album_id, library_id, directory
                    )
                return artist_cache[name]

            track_artist_ids = [artist_id_for(name) for name in _unique_labels(metadata.artists)]
            album_artist_ids = [
                artist_id_for(name) for name in _unique_labels(metadata.album_artists)
            ]
            connection.execute(delete(track_artists).where(track_artists.c.track_id == track_id))
            for position, artist_id in enumerate(track_artist_ids):
                connection.execute(
                    insert(track_artists).values(
                        track_id=track_id, artist_id=artist_id, position=position, role="artist"
                    )
                )
            if album_id is not None:
                connection.execute(
                    delete(album_artists).where(album_artists.c.album_id == album_id)
                )
                for position, artist_id in enumerate(album_artist_ids):
                    connection.execute(
                        insert(album_artists).values(
                            album_id=album_id,
                            artist_id=artist_id,
                            position=position,
                            role="album_artist",
                        )
                    )
            connection.execute(delete(track_genres).where(track_genres.c.track_id == track_id))
            for position, name in enumerate(_unique_labels(metadata.genres)):
                genre_id = connection.execute(
                    select(genres.c.id).where(genres.c.name == name)
                ).scalar_one_or_none()
                if genre_id is None:
                    genre_id = _insert_id(connection, genres, {"name": name})
                connection.execute(
                    insert(track_genres).values(
                        track_id=track_id, genre_id=genre_id, position=position
                    )
                )

            artwork_id: int | None = None
            cover_source: str | None = None
            cover_relative_path: str | None = None
            if metadata.artwork is not None:
                artwork = metadata.artwork
                digest = hashlib.sha256(artwork.data).hexdigest()
                existing_art = connection.execute(
                    select(artworks.c.id).where(artworks.c.sha256 == digest)
                ).scalar_one_or_none()
                artwork_id = (
                    int(existing_art)
                    if existing_art is not None
                    else _insert_id(
                        connection,
                        artworks,
                        {
                            "sha256": digest,
                            "data": artwork.data,
                            "mime": artwork.mime_type,
                            "width": artwork.width,
                            "height": artwork.height,
                        },
                    )
                )
                cover_source = artwork.source
                if artwork.source == "album.jpg":
                    # Conservar la ubicación de búsqueda, incluso si album.jpg es un enlace.
                    cover_relative_path = (relative.parent / "album.jpg").as_posix()
            file_values: dict[str, Any] = {
                "library_id": library_id,
                "relative_path": relative.as_posix(),
                "track_id": track_id,
                "format": metadata.audio_format.upper() if metadata.audio_format else None,
                "duration_seconds": metadata.duration_seconds,
                "sample_rate_hz": metadata.sample_rate_hz,
                "channels": metadata.channels,
                "bits_per_sample": metadata.bits_per_sample,
                "cover_artwork_id": artwork_id,
                "cover_source": cover_source,
                "cover_relative_path": cover_relative_path,
            }
            if existing_file is None:
                file_id = _insert_id(connection, audio_files, file_values)
            else:
                file_id = int(existing_file.id)
                connection.execute(
                    update(audio_files).where(audio_files.c.id == file_id).values(**file_values)
                )
            connection.execute(delete(raw_tags).where(raw_tags.c.file_id == file_id))
            for tag in metadata.raw_tags:
                connection.execute(
                    insert(raw_tags).values(
                        file_id=file_id, key=tag.key, value=tag.value, position=tag.position
                    )
                )
        return SaveOutcome(file_id, track_id, "created" if existing_file is None else "updated")

    def get(self, file_id: int) -> CatalogEntry | None:
        with self.engine.connect() as connection:
            record = (
                connection.execute(
                    select(
                        audio_files,
                        libraries.c.root_path,
                        tracks.c.title,
                        tracks.c.track_number,
                        tracks.c.track_total,
                        tracks.c.disc_number,
                        tracks.c.disc_total,
                        tracks.c.lyrics,
                        albums.c.id.label("album_id"),
                        albums.c.title.label("album_title"),
                        albums.c.year.label("album_year"),
                        albums.c.date.label("album_date"),
                    )
                    .join(libraries, libraries.c.id == audio_files.c.library_id)
                    .join(tracks, tracks.c.id == audio_files.c.track_id)
                    .outerjoin(albums, albums.c.id == tracks.c.album_id)
                    .where(audio_files.c.id == file_id)
                )
                .mappings()
                .one_or_none()
            )
            if record is None:
                return None
            track_id = int(record["track_id"])
            track_artist_names: tuple[str, ...] = tuple(
                connection.execute(
                    select(artists.c.name)
                    .join(track_artists, track_artists.c.artist_id == artists.c.id)
                    .where(track_artists.c.track_id == track_id)
                    .order_by(track_artists.c.position)
                ).scalars()
            )
            album_artist_names: tuple[str, ...] = (
                tuple(
                    connection.execute(
                        select(artists.c.name)
                        .join(album_artists, album_artists.c.artist_id == artists.c.id)
                        .where(album_artists.c.album_id == record["album_id"])
                        .order_by(album_artists.c.position)
                    ).scalars()
                )
                if record["album_id"] is not None
                else ()
            )
            genre_names: tuple[str, ...] = tuple(
                connection.execute(
                    select(genres.c.name)
                    .join(track_genres, track_genres.c.genre_id == genres.c.id)
                    .where(track_genres.c.track_id == track_id)
                    .order_by(track_genres.c.position)
                ).scalars()
            )
            raw = tuple(
                RawTagValue(key=row.key, value=row.value, position=row.position)
                for row in connection.execute(
                    select(raw_tags.c.key, raw_tags.c.value, raw_tags.c.position)
                    .where(raw_tags.c.file_id == file_id)
                    .order_by(raw_tags.c.key, raw_tags.c.position)
                )
            )
            artwork: Artwork | None = None
            if record["cover_artwork_id"] is not None:
                art = (
                    connection.execute(
                        select(artworks).where(artworks.c.id == record["cover_artwork_id"])
                    )
                    .mappings()
                    .one()
                )
                source_path = (
                    Path(record["root_path"]) / record["cover_relative_path"]
                    if record["cover_relative_path"] is not None
                    else None
                )
                artwork = Artwork(
                    data=bytes(art["data"]),
                    mime_type=art["mime"],
                    width=art["width"],
                    height=art["height"],
                    source=record["cover_source"],
                    source_path=source_path,
                )
            metadata = TrackMetadata(
                title=record["title"],
                album=record["album_title"],
                album_year=record["album_year"],
                album_date=record["album_date"],
                track_number=record["track_number"],
                track_total=record["track_total"],
                disc_number=record["disc_number"],
                disc_total=record["disc_total"],
                artists=track_artist_names,
                album_artists=album_artist_names,
                genres=genre_names,
                lyrics=record["lyrics"],
                artwork=artwork,
                raw_tags=raw,
                audio_format=str(record["format"]).lower(),
                duration_seconds=record["duration_seconds"],
                sample_rate_hz=record["sample_rate_hz"],
                channels=record["channels"],
                bits_per_sample=record["bits_per_sample"],
            )
            return CatalogEntry(
                file_id=file_id,
                track_id=track_id,
                library_root=Path(record["root_path"]),
                relative_path=record["relative_path"],
                metadata=metadata,
            )

    def list_entries(self) -> tuple[CatalogEntry, ...]:
        with self.engine.connect() as connection:
            file_ids: tuple[int, ...] = tuple(
                connection.execute(select(audio_files.c.id).order_by(audio_files.c.id)).scalars()
            )
        entries = (self.get(int(file_id)) for file_id in file_ids)
        return tuple(entry for entry in entries if entry is not None)

    def list_summaries(self) -> tuple[CatalogSummary, ...]:
        """Leer todas las filas de la lista sin cargar el detalle de cada archivo."""
        statement = (
            select(
                audio_files.c.id.label("file_id"),
                audio_files.c.track_id,
                audio_files.c.relative_path,
                tracks.c.title,
                albums.c.title.label("album_title"),
                albums.c.year.label("album_year"),
                artists.c.name.label("artist_name"),
            )
            .join(tracks, tracks.c.id == audio_files.c.track_id)
            .outerjoin(albums, albums.c.id == tracks.c.album_id)
            .outerjoin(track_artists, track_artists.c.track_id == tracks.c.id)
            .outerjoin(artists, artists.c.id == track_artists.c.artist_id)
            .order_by(audio_files.c.id, track_artists.c.position)
        )
        summaries: dict[int, CatalogSummary] = {}
        credits: dict[int, list[str]] = {}
        with self.engine.connect() as connection:
            for row in connection.execute(statement).mappings():
                file_id = int(row["file_id"])
                if file_id not in summaries:
                    summaries[file_id] = CatalogSummary(
                        file_id=file_id,
                        track_id=int(row["track_id"]),
                        title=row["title"],
                        artists=(),
                        album=row["album_title"],
                        album_year=row["album_year"],
                        relative_path=row["relative_path"],
                    )
                    credits[file_id] = []
                if row["artist_name"] is not None:
                    credits[file_id].append(row["artist_name"])
        return tuple(
            CatalogSummary(
                file_id=summary.file_id,
                track_id=summary.track_id,
                title=summary.title,
                artists=tuple(credits[file_id]),
                album=summary.album,
                album_year=summary.album_year,
                relative_path=summary.relative_path,
            )
            for file_id, summary in summaries.items()
        )
