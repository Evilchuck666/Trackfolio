"""Valores de edición del catálogo independientes de interfaces y persistencia."""

from __future__ import annotations

from dataclasses import dataclass, fields
from typing import Literal, cast

from trackfolio.domain.metadata import TrackMetadata

EditField = Literal[
    "title",
    "artists",
    "album",
    "album_year",
    "track_number",
    "track_total",
    "disc_number",
    "disc_total",
    "genres",
    "lyrics",
]
EditValue = str | int | tuple[str, ...] | None
EDIT_FIELDS: tuple[EditField, ...] = (
    "title",
    "artists",
    "album",
    "album_year",
    "track_number",
    "track_total",
    "disc_number",
    "disc_total",
    "genres",
    "lyrics",
)


@dataclass(frozen=True, slots=True)
class EditableValues:
    title: str | None = None
    artists: tuple[str, ...] = ()
    album: str | None = None
    album_year: int | None = None
    track_number: int | None = None
    track_total: int | None = None
    disc_number: int | None = None
    disc_total: int | None = None
    genres: tuple[str, ...] = ()
    lyrics: str | None = None

    def as_dict(self) -> dict[EditField, EditValue]:
        return {
            cast(EditField, field.name): cast(EditValue, getattr(self, field.name))
            for field in fields(self)
        }

    @classmethod
    def from_metadata(cls, metadata: TrackMetadata) -> EditableValues:
        return cls(**{field.name: getattr(metadata, field.name) for field in fields(cls)})


@dataclass(frozen=True, slots=True)
class EditableTrack:
    file_id: int
    track_id: int
    values: EditableValues
    token: str


@dataclass(frozen=True, slots=True)
class ArtistChoice:
    name: str
    artist_id: int | None = None


@dataclass(frozen=True, slots=True)
class FieldChange:
    field: EditField
    value: EditValue


@dataclass(frozen=True, slots=True)
class TrackEditPatch:
    changes: tuple[FieldChange, ...] = ()

    @property
    def empty(self) -> bool:
        return not self.changes

    def as_dict(self) -> dict[EditField, EditValue]:
        return {change.field: change.value for change in self.changes}


@dataclass(frozen=True, slots=True)
class FieldError:
    field: EditField
    message: str
