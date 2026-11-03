"""Group physical editions without merging compilations or unrelated folders."""

import hashlib
import json
import re
from collections import defaultdict
from pathlib import PurePosixPath
from typing import Protocol

from trackfolio.domain.album import Album, AlbumTrack


class AlbumReader(Protocol):
    def list_album_tracks(self) -> tuple[AlbumTrack, ...]: ...


def group_albums(tracks: tuple[AlbumTrack, ...]) -> tuple[Album, ...]:
    groups: dict[str, list[AlbumTrack]] = defaultdict(list)
    directories: dict[str, str] = {}
    for track in tracks:
        folder = PurePosixPath(track.summary.relative_path).parent
        disc = re.fullmatch(r"(?:cd|disc|disk|disco)[ _.-]*(\d+)", folder.name, re.IGNORECASE)
        if disc and track.disc_number is not None and int(disc[1]) == track.disc_number:
            folder = folder.parent
        directory = folder.as_posix()
        identity = (
            track.library_id,
            directory,
            track.summary.album,
            track.summary.album_year,
            track.album_date,
            track.album_artists,
            track.disc_total,
        )
        key = hashlib.sha256(json.dumps(identity, ensure_ascii=False).encode("utf-8")).hexdigest()
        groups[key].append(track)
        directories[key] = directory
    result = []
    for key, members in groups.items():
        members.sort(
            key=lambda t: (
                t.disc_number or 1,
                t.track_number is None,
                t.track_number or 0,
                t.summary.relative_path,
                t.summary.file_id,
            )
        )
        first = members[0]
        result.append(
            Album(
                key,
                first.summary.album,
                first.summary.album_year,
                first.album_artists,
                first.library_root,
                directories[key],
                tuple(members),
            )
        )
    return tuple(
        sorted(
            result,
            key=lambda a: (
                (a.title or "").casefold(),
                a.artists,
                a.year or 0,
                str(a.library_root),
                a.directory,
                a.key,
            ),
        )
    )


class ListAlbums:
    def __init__(self, reader: AlbumReader) -> None:
        self.reader = reader

    def execute(self) -> tuple[Album, ...]:
        return group_albums(self.reader.list_album_tracks())
