"""Observe tag writes without importing over unrelated catalogue corrections."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath
from typing import cast

from sqlalchemy import Connection, delete, insert, select, update

from trackfolio.application.write_tags import TagWriteConflict, TagWriteError
from trackfolio.domain.metadata import TrackMetadata
from trackfolio.domain.tag_write import AlbumNfoTrack, TagCatalogSnapshot
from trackfolio.infrastructure.catalog import separate_shared_track
from trackfolio.infrastructure.catalog_edit import (
    SqliteCatalogEditSessionFactory,
    _read_snapshot,
    _SqliteCatalogEditSession,
)
from trackfolio.infrastructure.database import audio_files, libraries, raw_tags, tracks


def _snapshot(connection: Connection, file_id: int) -> TagCatalogSnapshot:
    snapshot = _read_snapshot(connection, file_id)
    if snapshot is None:
        raise TagWriteConflict("La canción ya no existe en el catálogo.")
    raw = tuple(
        tuple(row)
        for row in connection.execute(
            select(raw_tags.c.key, raw_tags.c.position, raw_tags.c.value)
            .where(raw_tags.c.file_id == file_id)
            .order_by(raw_tags.c.key, raw_tags.c.position)
        )
    )
    token = hashlib.sha256(json.dumps((snapshot.editable.token, raw)).encode()).hexdigest()
    return TagCatalogSnapshot(
        file_id,
        Path(snapshot.file["root_path"]),
        snapshot.file["relative_path"],
        snapshot.editable.values,
        snapshot.album.get("date") if snapshot.album else None,
        token,
    )


class SqliteTagCatalog:
    def __init__(self) -> None:
        self._factory = SqliteCatalogEditSessionFactory()

    def snapshot(self, path: Path, file_id: int) -> TagCatalogSnapshot:
        session = cast(_SqliteCatalogEditSession, self._factory.open_reader(path))
        try:
            with session._engine.connect() as connection:
                return _snapshot(connection, file_id)
        finally:
            session.close()

    def album_tracks(self, path: Path, root: Path, folder: Path) -> tuple[AlbumNfoTrack, ...]:
        # The catalogue retains the imported root spelling; filesystem callers
        # supply canonical folders, including macOS /private/var aliases.
        relative_folder = PurePosixPath(folder.resolve().relative_to(root.resolve()).as_posix())
        session = cast(_SqliteCatalogEditSession, self._factory.open_reader(path))
        try:
            with session._engine.connect() as connection, connection.begin():
                query = (
                    select(audio_files.c.id, audio_files.c.relative_path)
                    .join(libraries, libraries.c.id == audio_files.c.library_id)
                    .where(libraries.c.root_path == root.as_posix())
                    .order_by(audio_files.c.relative_path)
                )
                if relative_folder != PurePosixPath("."):
                    query = query.where(
                        audio_files.c.relative_path.startswith(
                            relative_folder.as_posix() + "/",
                            autoescape=True,
                        )
                    )
                records = connection.execute(query).all()
                result = []
                for record in records:
                    if PurePosixPath(record.relative_path).parent != relative_folder:
                        continue
                    snapshot = _read_snapshot(connection, record.id)
                    if snapshot is None:
                        raise TagWriteConflict("Una pista dejó de estar disponible.")
                    values = snapshot.editable.values
                    result.append(
                        AlbumNfoTrack(
                            record.id,
                            record.relative_path,
                            values.album,
                            values.album_year,
                            tuple(
                                name
                                for role, _, name in snapshot.album_credits
                                if role == "album_artist"
                            ),
                            values.artists,
                            values.genres,
                            values.title,
                            values.track_number,
                            values.disc_number,
                        )
                    )
                return tuple(result)
        finally:
            session.close()

    def prepare(self, path: Path) -> None:
        session = self._factory.open_writer(path)
        session.close()

    def check(self, path: Path, snapshot: TagCatalogSnapshot) -> None:
        if self.snapshot(path, snapshot.file_id).token != snapshot.token:
            raise TagWriteConflict("El catálogo cambió. Revisa otra vez las diferencias.")

    def confirm(
        self, path: Path, snapshot: TagCatalogSnapshot, observed: TrackMetadata, date_written: bool
    ) -> None:
        session = cast(_SqliteCatalogEditSession, self._factory.open_writer(path))
        try:
            with session._engine.begin() as connection:
                connection.exec_driver_sql("ROLLBACK")
                connection.exec_driver_sql("BEGIN IMMEDIATE")
                session._repository._validate_write_schema(connection)
                current = _snapshot(connection, snapshot.file_id)
                if current.token != snapshot.token:
                    actual_tags = tuple(
                        tuple(row)
                        for row in connection.execute(
                            select(raw_tags.c.key, raw_tags.c.position, raw_tags.c.value)
                            .where(raw_tags.c.file_id == snapshot.file_id)
                            .order_by(raw_tags.c.key, raw_tags.c.position)
                        )
                    )
                    expected_tags = tuple(
                        sorted((tag.key, tag.position, tag.value) for tag in observed.raw_tags)
                    )
                    if (
                        current.values == snapshot.values
                        and current.library_root == snapshot.library_root
                        and current.relative_path == snapshot.relative_path
                        and current.album_date
                        == (observed.album_date if date_written else snapshot.album_date)
                        and actual_tags == expected_tags
                    ):
                        return  # The transaction committed before its acknowledgement was lost.
                    raise TagWriteConflict(
                        "Las etiquetas se escribieron, pero el catálogo cambió. "
                        "Sus nuevas correcciones se han conservado."
                    )
                if date_written and snapshot.album_date != observed.album_date:
                    original = _read_snapshot(connection, snapshot.file_id)
                    if original is None:
                        raise TagWriteError("La canción dejó de estar disponible.")
                    track_id = separate_shared_track(
                        connection, snapshot.file_id, original.editable.track_id
                    )
                    album_id = session._edited_album_id(
                        connection, original, {"album_date": observed.album_date}
                    )
                    connection.execute(
                        update(tracks).where(tracks.c.id == track_id).values(album_id=album_id)
                    )
                connection.execute(delete(raw_tags).where(raw_tags.c.file_id == snapshot.file_id))
                for value in observed.raw_tags:
                    connection.execute(
                        insert(raw_tags).values(
                            file_id=snapshot.file_id,
                            key=value.key,
                            value=value.value,
                            position=value.position,
                        )
                    )
        finally:
            session.close()
