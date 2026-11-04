"""Read and partially update the catalog without Qt, ORM or audio access."""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Protocol, cast

from trackfolio.application.catalog import CatalogAccessError
from trackfolio.domain.catalog import CatalogEntry, CatalogSummary
from trackfolio.domain.catalog_edit import (
    BATCH_EDIT_FIELDS,
    EDIT_FIELDS,
    ArtistChoice,
    EditableTrack,
    EditableValues,
    EditField,
    EditValue,
    FieldChange,
    FieldError,
    TrackEditPatch,
)


class CatalogEditError(CatalogAccessError):
    """Recoverable editing failure with a message suitable for any interface."""

    def __init__(self, message: str, *, backup_path: Path | None = None) -> None:
        self.backup_path = backup_path
        super().__init__(message)


class CatalogEditConflict(CatalogEditError):
    """The record or its relationships changed after the draft was prepared."""


class CatalogRecordMissing(CatalogEditError):
    """The selected file no longer exists in the catalog."""


class CatalogEditValidationError(CatalogEditError):
    def __init__(self, errors: tuple[FieldError, ...]) -> None:
        self.errors = errors
        super().__init__("Check the highlighted fields before saving.")


@dataclass(frozen=True, slots=True)
class CatalogEditOutcome:
    entry: CatalogEntry
    summary: CatalogSummary
    backup_path: Path | None = None
    warning: str | None = None


class CatalogEditRepository(Protocol):
    def get_editable(self, file_id: int) -> EditableTrack | None: ...

    def find_artists(self, query: str) -> tuple[ArtistChoice, ...]: ...

    def find_genres(self, query: str) -> tuple[str, ...]: ...

    def apply_edit(self, original: EditableTrack, patch: TrackEditPatch) -> CatalogEditOutcome: ...

    def apply_edits(
        self, originals: tuple[EditableTrack, ...], patch: TrackEditPatch
    ) -> tuple[CatalogEditOutcome, ...]: ...


class CatalogEditSession(CatalogEditRepository, Protocol):
    database_path: Path
    backup_path: Path | None

    def close(self) -> None: ...


class CatalogEditSessionFactory(Protocol):
    def open_reader(self, database_path: Path) -> CatalogEditSession: ...

    def open_writer(self, database_path: Path) -> CatalogEditSession: ...


_NUMERIC_FIELDS = frozenset(
    ("album_year", "track_number", "track_total", "disc_number", "disc_total")
)


def validate_edit_patch(values: EditableValues, patch: TrackEditPatch) -> TrackEditPatch:
    """Normalize only requested values, keeping absent and cleared fields distinct."""
    errors: list[FieldError] = []
    normalized: dict[EditField, EditValue] = {}
    previous = values.as_dict()
    seen: set[EditField] = set()
    for change in patch.changes:
        field, value = change.field, change.value
        if field not in EDIT_FIELDS:
            raise CatalogEditError("The change contains a field that cannot be edited.")
        if field in seen:
            errors.append(FieldError(field, "The field appears more than once in the request."))
            continue
        seen.add(field)
        if field in _NUMERIC_FIELDS:
            if isinstance(value, str):
                text = value.strip()
                if not text:
                    value = None
                elif re.fullmatch(r"[0-9]{1,19}", text):
                    value = int(text)
                else:
                    errors.append(FieldError(field, "Enter a positive integer or leave blank."))
                    continue
            maximum = 9999 if field == "album_year" else 2**63 - 1
            if value is not None and (type(value) is not int or not 1 <= value <= maximum):
                message = (
                    "Enter a year between 1 and 9999 or leave blank."
                    if field == "album_year"
                    else "Enter a positive integer within the range supported by the catalog."
                )
                errors.append(FieldError(field, message))
                continue
        elif field in ("artists", "genres", "album_artists"):
            if not isinstance(value, tuple) or any(not isinstance(item, str) for item in value):
                errors.append(FieldError(field, "Enter a list of full names."))
                continue
            value = tuple(dict.fromkeys(item for item in value if item.strip()))
        else:
            if value is not None and not isinstance(value, str):
                errors.append(FieldError(field, "Enter text or leave the field blank."))
                continue
            if isinstance(value, str) and (
                value == "" or (field != "lyrics" and not value.strip())
            ):
                value = None
        if previous[field] != value:
            normalized[field] = value
    for number, total in (("track_number", "track_total"), ("disc_number", "disc_total")):
        number_field, total_field = cast(EditField, number), cast(EditField, total)
        if number_field in normalized or total_field in normalized:
            resulting_number = normalized.get(number_field, previous[number_field])
            resulting_total = normalized.get(total_field, previous[total_field])
            if (
                type(resulting_number) is int
                and type(resulting_total) is int
                and resulting_number > resulting_total
            ):
                errors.append(FieldError(number_field, "The number cannot exceed its total."))
                errors.append(FieldError(total_field, "The total cannot be less than the number."))
    if errors:
        raise CatalogEditValidationError(tuple(errors))
    return TrackEditPatch(tuple(FieldChange(field, value) for field, value in normalized.items()))


class GetEditableTrack:
    def __init__(self, repository: CatalogEditRepository) -> None:
        self.repository = repository

    def execute(self, file_id: int) -> EditableTrack | None:
        return self.repository.get_editable(file_id)


class FindArtists:
    def __init__(self, repository: CatalogEditRepository) -> None:
        self.repository = repository

    def execute(self, query: str) -> tuple[ArtistChoice, ...]:
        return self.repository.find_artists(query)


class FindGenres:
    def __init__(self, repository: CatalogEditRepository) -> None:
        self.repository = repository

    def execute(self, query: str) -> tuple[str, ...]:
        return self.repository.find_genres(query)


class UpdateCatalogTrack:
    def __init__(self, factory: CatalogEditSessionFactory) -> None:
        self.factory = factory

    def execute(
        self, database_path: Path, original: EditableTrack, patch: TrackEditPatch
    ) -> CatalogEditOutcome | None:
        normalized = validate_edit_patch(original.values, patch)
        if normalized.empty:
            return None
        session = self.factory.open_writer(database_path)
        try:
            outcome = session.apply_edit(original, normalized)
        except Exception as exc:
            if isinstance(exc, CatalogEditError):
                exc.backup_path = session.backup_path
            try:
                session.close()
            except Exception as cleanup:
                exc.add_note(f"Could not close catalog access: {cleanup}")
            raise
        try:
            session.close()
        except Exception as exc:
            return replace(
                outcome,
                warning=f"Changes were saved, but access could not be closed: {exc}",
            )
        return outcome


def validate_batch_edit(originals: tuple[EditableTrack, ...], patch: TrackEditPatch) -> None:
    if not originals or len({item.file_id for item in originals}) != len(originals):
        raise CatalogEditError("Select distinct songs for batch editing.")
    if any(change.field not in BATCH_EDIT_FIELDS for change in patch.changes):
        raise CatalogEditError(
            "Batch editing supports only album, track or album artists, year and genres."
        )
    for original in originals:
        validate_edit_patch(original.values, patch)


class UpdateCatalogTracks:
    """Apply explicitly chosen common values in a single catalog transaction."""

    def __init__(self, factory: CatalogEditSessionFactory) -> None:
        self.factory = factory

    def execute(
        self, database_path: Path, originals: tuple[EditableTrack, ...], patch: TrackEditPatch
    ) -> tuple[CatalogEditOutcome, ...]:
        validate_batch_edit(originals, patch)
        if all(validate_edit_patch(item.values, patch).empty for item in originals):
            return ()
        session = self.factory.open_writer(database_path)
        try:
            outcomes = session.apply_edits(originals, patch)
        except Exception as exc:
            if isinstance(exc, CatalogEditError):
                exc.backup_path = session.backup_path
            try:
                session.close()
            except Exception as cleanup:
                exc.add_note(f"Could not close catalog access: {cleanup}")
            raise
        try:
            session.close()
        except Exception as exc:
            return tuple(
                replace(
                    outcome,
                    warning=f"Changes were saved, but access could not be closed: {exc}",
                )
                for outcome in outcomes
            )
        return outcomes
