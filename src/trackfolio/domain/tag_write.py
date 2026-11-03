"""Immutable intentions and results for writing saved catalogue values to audio."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from trackfolio.domain.catalog_edit import EditableValues, EditField, EditValue

TagItemState = Literal["ready", "unchanged", "blocked", "conflict"]
TagResultState = Literal[
    "confirmed", "catalog_pending", "unchanged", "excluded", "conflict", "failed", "pending"
]


@dataclass(frozen=True, slots=True)
class FileFingerprint:
    device: int
    inode: int
    size: int
    modified_ns: int
    sha256: str


@dataclass(frozen=True, slots=True)
class AlbumNfoTrack:
    file_id: int
    relative_path: str
    album: str | None
    year: int | None
    album_artists: tuple[str, ...]
    artists: tuple[str, ...]
    genres: tuple[str, ...]
    title: str | None = None
    track_number: int | None = None
    disc_number: int | None = None


@dataclass(frozen=True, slots=True)
class AlbumNfoSong:
    file_id: int
    title: str | None
    track_number: int | None
    disc_number: int | None
    update_title: bool


@dataclass(frozen=True, slots=True)
class AlbumNfoValues:
    title: str | None
    year: int | None
    genres: tuple[str, ...]
    artists: tuple[str, ...] | None  # None preserves existing compilation credits.
    songs: tuple[AlbumNfoSong, ...] = ()


@dataclass(frozen=True, slots=True)
class AlbumNfoItem:
    path: Path
    library_root: Path
    file_ids: tuple[int, ...]
    tracks: tuple[AlbumNfoTrack, ...] = ()
    members: tuple[str, ...] = ()
    values: AlbumNfoValues | None = None
    fingerprint: FileFingerprint | None = None
    state: Literal["ready", "unchanged", "absent", "blocked", "conflict"] = "blocked"
    message: str = ""


@dataclass(frozen=True, slots=True)
class AlbumNfoResult:
    path: Path
    state: Literal["updated", "unchanged", "absent", "pending", "conflict", "failed"]
    message: str = ""
    backup_path: Path | None = None
    published: bool = False


@dataclass(frozen=True, slots=True)
class TagCatalogSnapshot:
    file_id: int
    library_root: Path
    relative_path: str
    values: EditableValues
    album_date: str | None
    token: str


@dataclass(frozen=True, slots=True)
class TagWriteRequest:
    database_path: Path
    file_ids: tuple[int, ...]
    fields: tuple[EditField, ...]
    allow_date_loss: bool = False
    lyrics_keys: tuple[tuple[int, str], ...] = ()


@dataclass(frozen=True, slots=True)
class TagDifference:
    field: EditField
    before: EditValue
    after: EditValue
    physical_tags: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PlannedTags:
    before: EditableValues
    after: EditableValues
    before_date: str | None
    after_date: str | None
    audio_format: str
    version: str
    differences: tuple[TagDifference, ...]
    lyrics_keys: tuple[str, ...] = ()
    selected_lyrics: str | None = None
    error: str | None = None


@dataclass(frozen=True, slots=True)
class TagWriteItem:
    file_id: int
    path: Path
    snapshot: TagCatalogSnapshot | None
    fingerprint: FileFingerprint | None
    tags: PlannedTags | None
    state: TagItemState
    message: str = ""


@dataclass(frozen=True, slots=True)
class TagWritePreview:
    operation_id: str
    request: TagWriteRequest
    catalog_identity: tuple[int, int]
    items: tuple[TagWriteItem, ...]
    nfo_items: tuple[AlbumNfoItem, ...] = ()


@dataclass(frozen=True, slots=True)
class TagWriteProgress:
    phase: str
    processed: int
    total: int
    path: Path | None = None


@dataclass(frozen=True, slots=True)
class TagWriteResult:
    file_id: int
    path: Path
    state: TagResultState
    message: str = ""
    backup_path: Path | None = None


@dataclass(frozen=True, slots=True)
class TagWriteReport:
    operation_id: str
    results: tuple[TagWriteResult, ...]
    journal_path: Path | None = None
    cancelled: bool = False
    fatal_error: str | None = None
    nfo_results: tuple[AlbumNfoResult, ...] = ()


@dataclass(frozen=True, slots=True)
class PendingTagOperation:
    journal_path: Path
    database_path: Path | None
    description: str


@dataclass(frozen=True, slots=True)
class TagRecoveryState:
    state: str
    after_hash: str | None
    temporary_identity: tuple[int, int] | None = None
