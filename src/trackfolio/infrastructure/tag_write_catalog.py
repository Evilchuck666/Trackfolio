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
from trackfolio.infrastructure.database import artworks, audio_files, libraries, raw_tags, tracks


def _snapshot(connection: Connection, file_id: int) -> TagCatalogSnapshot:
    snapshot = _read_snapshot(connection, file_id)
    if snapshot is None:
        raise TagWriteConflict("The song no longer exists in the catalog.")
    raw = tuple(
        tuple(row)
        for row in connection.execute(
            select(raw_tags.c.key, raw_tags.c.position, raw_tags.c.value)
            .where(raw_tags.c.file_id == file_id)
            .order_by(raw_tags.c.key, raw_tags.c.position)
        )
    )
    token = hashlib.sha256(json.dumps((snapshot.editable.token, raw)).encode()).hexdigest()
    cover = (
        connection.execute(
            select(artworks.c.data).where(artworks.c.id == snapshot.file["cover_artwork_id"])
        ).scalar_one()
        if snapshot.file["cover_artwork_id"] is not None
        else None
    )
    return TagCatalogSnapshot(
        file_id,
        Path(snapshot.file["root_path"]),
        snapshot.file["relative_path"],
        snapshot.editable.values,
        snapshot.album.get("date") if snapshot.album else None,
        token,
        hashlib.sha256(cover).hexdigest() if cover is not None else None,
        snapshot.file["cover_source"],
        snapshot.file["cover_relative_path"],
        True,
    )


def _same_cover(first: TagCatalogSnapshot, second: TagCatalogSnapshot) -> bool:
    return not first.cover_known or (
        first.cover_sha256,
        first.cover_source,
        first.cover_relative_path,
    ) == (second.cover_sha256, second.cover_source, second.cover_relative_path)


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
                        raise TagWriteConflict("A track is no longer available.")
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
        current = self.snapshot(path, snapshot.file_id)
        if current.token != snapshot.token or not _same_cover(snapshot, current):
            raise TagWriteConflict("The catalog changed. Review the differences again.")

    def confirm(
        self,
        path: Path,
        snapshot: TagCatalogSnapshot,
        observed: TrackMetadata,
        date_written: bool,
        cover_written: bool = False,
    ) -> None:
        session = cast(_SqliteCatalogEditSession, self._factory.open_writer(path))
        try:
            with session._engine.begin() as connection:
                connection.exec_driver_sql("ROLLBACK")
                connection.exec_driver_sql("BEGIN IMMEDIATE")
                session._repository._validate_write_schema(connection)
                current = _snapshot(connection, snapshot.file_id)
                if current.token != snapshot.token or not _same_cover(snapshot, current):
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
                        and (
                            (
                                observed.artwork is not None
                                and current.cover_sha256
                                == hashlib.sha256(observed.artwork.data).hexdigest()
                                and current.cover_source == "embedded"
                                and current.cover_relative_path is None
                            )
                            if cover_written
                            else _same_cover(snapshot, current)
                        )
                    ):
                        return  # The transaction committed before its acknowledgement was lost.
                    raise TagWriteConflict(
                        "The tags were written, but the catalog changed. "
                        "Sus nuevas correcciones se han conservado."
                    )
                if date_written and snapshot.album_date != observed.album_date:
                    original = _read_snapshot(connection, snapshot.file_id)
                    if original is None:
                        raise TagWriteError("The song is no longer available.")
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
                if cover_written:
                    artwork = observed.artwork
                    if artwork is None or artwork.source != "embedded":
                        raise TagWriteError("The observed cover is not embedded in the song.")
                    digest = hashlib.sha256(artwork.data).hexdigest()
                    artwork_id: int | None = connection.execute(
                        select(artworks.c.id).where(artworks.c.sha256 == digest)
                    ).scalar_one_or_none()
                    if artwork_id is None:
                        artwork_id = connection.execute(
                            insert(artworks)
                            .values(
                                sha256=digest,
                                data=artwork.data,
                                mime=artwork.mime_type,
                                width=artwork.width,
                                height=artwork.height,
                            )
                            .returning(artworks.c.id)
                        ).scalar_one()
                    connection.execute(
                        update(audio_files)
                        .where(audio_files.c.id == snapshot.file_id)
                        .values(
                            cover_artwork_id=artwork_id,
                            cover_source="embedded",
                            cover_relative_path=None,
                        )
                    )
        finally:
            session.close()
