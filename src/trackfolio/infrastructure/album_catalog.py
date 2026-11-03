"""Lightweight album queries: no images, lyrics or access to music files."""

from pathlib import Path
from typing import cast

from sqlalchemy import Connection, select

from trackfolio.domain.album import AlbumTrack
from trackfolio.infrastructure.database import (
    album_artists,
    albums,
    artists,
    audio_files,
    genres,
    libraries,
    track_genres,
    tracks,
)


def read_album_tracks(connection: Connection) -> tuple[AlbumTrack, ...]:
    from trackfolio.infrastructure.catalog import SqliteCatalogRepository

    summaries = {
        summary.file_id: summary
        for summary in SqliteCatalogRepository.summaries_from_connection(connection)
    }
    credits: dict[int, list[str]] = {}
    for album_id, name in connection.execute(
        select(album_artists.c.album_id, artists.c.name)
        .join(artists, artists.c.id == album_artists.c.artist_id)
        .where(album_artists.c.role == "album_artist")
        .order_by(album_artists.c.album_id, album_artists.c.position)
    ):
        credits.setdefault(cast(int, album_id), []).append(cast(str, name))
    labels: dict[int, list[str]] = {}
    for track_id, name in connection.execute(
        select(track_genres.c.track_id, genres.c.name)
        .join(genres, genres.c.id == track_genres.c.genre_id)
        .order_by(track_genres.c.track_id, track_genres.c.position)
    ):
        labels.setdefault(cast(int, track_id), []).append(cast(str, name))
    query = (
        select(
            audio_files.c.id,
            audio_files.c.library_id,
            libraries.c.root_path,
            tracks.c.album_id,
            albums.c.date,
            tracks.c.disc_number,
            tracks.c.disc_total,
            tracks.c.track_number,
            audio_files.c.duration_seconds,
            audio_files.c.cover_artwork_id,
        )
        .join(tracks, tracks.c.id == audio_files.c.track_id)
        .join(libraries, libraries.c.id == audio_files.c.library_id)
        .outerjoin(albums, albums.c.id == tracks.c.album_id)
        .order_by(audio_files.c.id)
    )
    return tuple(
        AlbumTrack(
            summaries[row.id],
            row.library_id,
            Path(row.root_path),
            tuple(credits.get(row.album_id, ())),
            row.date,
            row.disc_number,
            row.disc_total,
            row.track_number,
            row.duration_seconds,
            tuple(labels.get(summaries[row.id].track_id, ())),
            row.cover_artwork_id is not None,
        )
        for row in connection.execute(query)
    )
