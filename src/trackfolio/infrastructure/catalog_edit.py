"""Edición SQLite por archivo con comparación y conservación de relaciones."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, cast

from sqlalchemy import URL, Connection, Engine, create_engine, delete, func, insert, select, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.pool import NullPool

from trackfolio.application.edit_catalog import (
    CatalogEditConflict,
    CatalogEditError,
    CatalogEditOutcome,
    CatalogEditSession,
    CatalogRecordMissing,
    validate_edit_patch,
)
from trackfolio.domain.catalog_edit import (
    ArtistChoice,
    EditableTrack,
    EditableValues,
    TrackEditPatch,
)
from trackfolio.infrastructure.catalog import (
    SqliteCatalogRepository,
    _insert_id,
    album_import_key,
    separate_shared_track,
)
from trackfolio.infrastructure.database import (
    _file_uri,
    album_artists,
    albums,
    artists,
    audio_files,
    genres,
    libraries,
    migrate_engine,
    track_artists,
    track_genres,
    tracks,
    writable_engine,
)
from trackfolio.infrastructure.session import _access_error, _validate_catalog


@dataclass(frozen=True)
class _Snapshot:
    editable: EditableTrack
    file: dict[str, Any]
    album: dict[str, Any] | None
    album_credits: tuple[tuple[str, int, str], ...]


def _read_snapshot(connection: Connection, file_id: int) -> _Snapshot | None:
    record = (
        connection.execute(
            select(audio_files, libraries.c.root_path)
            .join(libraries, libraries.c.id == audio_files.c.library_id)
            .where(audio_files.c.id == file_id)
        )
        .mappings()
        .one_or_none()
    )
    if record is None:
        return None
    file = dict(record)
    track_id = int(file["track_id"])
    track = dict(connection.execute(select(tracks).where(tracks.c.id == track_id)).mappings().one())
    album = (
        dict(
            connection.execute(select(albums).where(albums.c.id == track["album_id"]))
            .mappings()
            .one()
        )
        if track["album_id"] is not None
        else None
    )
    credits = tuple(
        (row.role, int(row.position), row.name)
        for row in connection.execute(
            select(track_artists.c.role, track_artists.c.position, artists.c.name)
            .join(artists, artists.c.id == track_artists.c.artist_id)
            .where(track_artists.c.track_id == track_id)
            .order_by(track_artists.c.role, track_artists.c.position)
        )
    )
    album_credits = (
        tuple(
            (row.role, int(row.position), row.name)
            for row in connection.execute(
                select(album_artists.c.role, album_artists.c.position, artists.c.name)
                .join(artists, artists.c.id == album_artists.c.artist_id)
                .where(album_artists.c.album_id == album["id"])
                .order_by(album_artists.c.role, album_artists.c.position)
            )
        )
        if album is not None
        else ()
    )
    genre_credits = tuple(
        (int(row.position), row.name)
        for row in connection.execute(
            select(track_genres.c.position, genres.c.name)
            .join(genres, genres.c.id == track_genres.c.genre_id)
            .where(track_genres.c.track_id == track_id)
            .order_by(track_genres.c.position)
        )
    )
    token = hashlib.sha256(
        json.dumps(
            {
                "file": file,
                "track": track,
                "album": album,
                "credits": credits,
                "album_credits": album_credits,
                "genres": genre_credits,
            },
            ensure_ascii=False,
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()
    values = EditableValues(
        title=track["title"],
        artists=tuple(name for role, _position, name in credits if role == "artist"),
        album=album["title"] if album is not None else None,
        album_year=album["year"] if album is not None else None,
        track_number=track["track_number"],
        track_total=track["track_total"],
        disc_number=track["disc_number"],
        disc_total=track["disc_total"],
        genres=tuple(name for _position, name in genre_credits),
        lyrics=track["lyrics"],
    )
    return _Snapshot(EditableTrack(file_id, track_id, values, token), file, album, album_credits)


class _SqliteCatalogEditSession:
    def __init__(
        self,
        path: Path,
        engine: Engine,
        *,
        writable: bool = False,
        backup_path: Path | None = None,
    ) -> None:
        self.database_path = path
        self.backup_path = backup_path
        self._engine = engine
        self._writable = writable
        self._closed = False
        self._repository = SqliteCatalogRepository(engine)

    def _check_open(self) -> None:
        if self._closed:
            raise CatalogEditError("El acceso de edición al catálogo está cerrado.")

    def get_editable(self, file_id: int) -> EditableTrack | None:
        self._check_open()
        try:
            with self._engine.connect() as connection:
                snapshot = _read_snapshot(connection, file_id)
                return snapshot.editable if snapshot is not None else None
        except SQLAlchemyError as exc:
            raise CatalogEditError(
                str(_access_error(exc, "No se pudo preparar la edición."))
            ) from exc

    def find_artists(self, query: str) -> tuple[ArtistChoice, ...]:
        self._check_open()
        try:
            with self._engine.connect() as connection:
                rows = connection.execute(
                    select(func.min(artists.c.id).label("artist_id"), artists.c.name)
                    .where(artists.c.name.contains(query, autoescape=True))
                    .group_by(artists.c.name)
                    .order_by(artists.c.name)
                    .limit(100)
                )
                # 001 puede contener varias filas con el mismo nombre exacto.
                choices: dict[str, ArtistChoice] = {}
                for row in rows:
                    choices.setdefault(row.name, ArtistChoice(row.name, int(row.artist_id)))
                return tuple(choices.values())
        except SQLAlchemyError as exc:
            raise CatalogEditError(
                str(_access_error(exc, "No se pudieron buscar artistas."))
            ) from exc

    def find_genres(self, query: str) -> tuple[str, ...]:
        self._check_open()
        try:
            with self._engine.connect() as connection:
                return tuple(
                    connection.execute(
                        select(genres.c.name)
                        .where(genres.c.name.contains(query, autoescape=True))
                        .order_by(genres.c.name)
                        .limit(100)
                    ).scalars()
                )
        except SQLAlchemyError as exc:
            raise CatalogEditError(
                str(_access_error(exc, "No se pudieron buscar géneros."))
            ) from exc

    def _edited_album_id(
        self, connection: Connection, snapshot: _Snapshot, changes: dict[str, Any]
    ) -> int | None:
        old_album = snapshot.album or {}
        title = changes.get("album", old_album.get("title"))
        year = changes.get("album_year", old_album.get("year"))
        date = old_album.get("date")
        disc_total = old_album.get("disc_total")
        credits = snapshot.album_credits
        if title is None and year is None and date is None and disc_total is None and not credits:
            return None
        library_id = int(snapshot.file["library_id"])
        directory = PurePosixPath(snapshot.file["relative_path"]).parent.as_posix()
        names = tuple(name for role, _position, name in credits if role == "album_artist")
        key = album_import_key(library_id, directory, title, date, year, disc_total, names)
        existing = (
            connection.execute(
                select(albums).where(albums.c.library_id == library_id, albums.c.import_key == key)
            )
            .mappings()
            .one_or_none()
        )
        if existing is not None:
            existing_credits = tuple(
                (row.role, int(row.position), row.name)
                for row in connection.execute(
                    select(album_artists.c.role, album_artists.c.position, artists.c.name)
                    .join(artists, artists.c.id == album_artists.c.artist_id)
                    .where(album_artists.c.album_id == existing["id"])
                    .order_by(album_artists.c.role, album_artists.c.position)
                )
            )
            target_names = tuple(
                name for role, _position, name in existing_credits if role == "album_artist"
            )
            additional = tuple(credit for credit in credits if credit[0] != "album_artist")
            target_additional = tuple(
                credit for credit in existing_credits if credit[0] != "album_artist"
            )
            target_fields = (
                existing["directory"],
                existing["title"],
                existing["date"],
                existing["year"],
                existing["disc_total"],
            )
            if (
                target_additional != additional
                or target_names != names
                or target_fields != (directory, title, date, year, disc_total)
            ):
                raise CatalogEditConflict(
                    "El álbum de destino tiene créditos diferentes. "
                    "Revisa la agrupación antes de guardar esta canción."
                )
            return int(existing["id"])
        album_id = _insert_id(
            connection,
            albums,
            {
                "library_id": library_id,
                "directory": directory,
                "import_key": key,
                "title": title,
                "year": year,
                "date": date,
                "disc_total": disc_total,
            },
        )
        for role, position, name in credits:
            connection.execute(
                insert(album_artists).values(
                    album_id=album_id,
                    role=role,
                    position=position,
                    artist_id=self._repository._artist_id(connection, name),
                )
            )
        return album_id

    def _write_patch(
        self, connection: Connection, snapshot: _Snapshot, patch: TrackEditPatch
    ) -> None:
        changes: dict[str, Any] = {str(field): value for field, value in patch.as_dict().items()}
        track_id = separate_shared_track(
            connection, snapshot.editable.file_id, snapshot.editable.track_id
        )
        track_values: dict[str, Any] = {
            field: value
            for field, value in changes.items()
            if field not in ("artists", "genres", "album", "album_year")
        }
        if "album" in changes or "album_year" in changes:
            track_values["album_id"] = self._edited_album_id(connection, snapshot, changes)
        if track_values:
            connection.execute(update(tracks).where(tracks.c.id == track_id).values(**track_values))
        if "artists" in changes:
            connection.execute(
                delete(track_artists).where(
                    track_artists.c.track_id == track_id, track_artists.c.role == "artist"
                )
            )
            for position, name in enumerate(cast(tuple[str, ...], changes["artists"])):
                connection.execute(
                    insert(track_artists).values(
                        track_id=track_id,
                        role="artist",
                        position=position,
                        artist_id=self._repository._artist_id(connection, name),
                    )
                )
        if "genres" in changes:
            connection.execute(delete(track_genres).where(track_genres.c.track_id == track_id))
            for position, name in enumerate(cast(tuple[str, ...], changes["genres"])):
                connection.execute(
                    sqlite_insert(genres)
                    .values(name=name)
                    .on_conflict_do_nothing(index_elements=[genres.c.name])
                )
                genre_id: int = connection.execute(
                    select(genres.c.id).where(genres.c.name == name)
                ).scalar_one()
                connection.execute(
                    insert(track_genres).values(
                        track_id=track_id, genre_id=genre_id, position=position
                    )
                )

    def apply_edit(self, original: EditableTrack, patch: TrackEditPatch) -> CatalogEditOutcome:
        self._check_open()
        if not self._writable:
            raise CatalogEditError("La sesión de consulta no permite guardar cambios.")
        normalized = validate_edit_patch(original.values, patch)
        try:
            with self._engine.begin() as connection:
                # autocommit=False inicia una transacción diferida: reservar el
                # escritor antes de leer evita comparar contra una versión vieja.
                connection.exec_driver_sql("ROLLBACK")
                connection.exec_driver_sql("BEGIN IMMEDIATE")
                self._repository._validate_write_schema(connection)
                snapshot = _read_snapshot(connection, original.file_id)
                if snapshot is None:
                    raise CatalogRecordMissing("La canción ya no existe en este catálogo.")
                if (
                    snapshot.editable.token != original.token
                    or snapshot.editable.track_id != original.track_id
                ):
                    raise CatalogEditConflict(
                        "La canción o sus relaciones cambiaron desde que empezaste a editar. "
                        "Recarga el registro para revisar los valores actuales."
                    )
                normalized = validate_edit_patch(snapshot.editable.values, normalized)
                if not normalized.empty:
                    self._write_patch(connection, snapshot, normalized)
                entry = self._repository.get_from_connection(connection, original.file_id)
                summary = self._repository.summary_from_connection(connection, original.file_id)
                if entry is None or summary is None:
                    raise CatalogRecordMissing("La canción ya no existe en este catálogo.")
            return CatalogEditOutcome(entry, summary, self.backup_path)
        except CatalogEditError as exc:
            exc.backup_path = self.backup_path
            raise
        except SQLAlchemyError as exc:
            message = str(_access_error(exc, "No se pudieron guardar los cambios en el catálogo."))
            error = CatalogEditError(message)
            error.backup_path = self.backup_path
            raise error from exc

    def close(self) -> None:
        if not self._closed:
            self._closed = True
            self._engine.dispose()


class SqliteCatalogEditSessionFactory:
    """Acceso de consulta intacto; el escritor actualiza un catálogo anterior."""

    @staticmethod
    def _path(path: Path) -> Path:
        try:
            database = path.expanduser().resolve(strict=True)
            if not database.is_file():
                raise CatalogEditError("Selecciona un archivo de catálogo existente.")
            return database
        except OSError as exc:
            raise CatalogEditError("No se pudo acceder al archivo de catálogo.") from exc

    def open_reader(self, database_path: Path) -> CatalogEditSession:
        database = self._path(database_path)
        engine = create_engine(
            URL.create("sqlite", database=_file_uri(database), query={"mode": "ro", "uri": "true"}),
            connect_args={"timeout": 2.0, "autocommit": False, "check_same_thread": False},
            poolclass=NullPool,
        )
        try:
            _validate_catalog(engine)
        except SQLAlchemyError as exc:
            engine.dispose()
            raise CatalogEditError(
                str(_access_error(exc, "No se pudo abrir el catálogo."))
            ) from exc
        except ValueError as exc:
            engine.dispose()
            raise CatalogEditError(str(exc)) from exc
        except BaseException:
            engine.dispose()
            raise
        return _SqliteCatalogEditSession(database, engine)

    def open_writer(self, database_path: Path) -> CatalogEditSession:
        database = self._path(database_path)
        engine = writable_engine(database)
        try:
            backup_path = migrate_engine(engine, database, require_catalog=True)
        except SQLAlchemyError as exc:
            engine.dispose()
            raise CatalogEditError(
                str(_access_error(exc, "No se pudo abrir el escritor."))
            ) from exc
        except (OSError, ValueError, TimeoutError, sqlite3.Error) as exc:
            engine.dispose()
            raise CatalogEditError(str(exc)) from exc
        except BaseException:
            engine.dispose()
            raise
        return _SqliteCatalogEditSession(database, engine, writable=True, backup_path=backup_path)
