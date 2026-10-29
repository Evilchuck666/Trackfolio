"""Lectura y actualización parcial del catálogo sin Qt, ORM ni acceso al audio."""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Protocol, cast

from trackfolio.application.catalog import CatalogAccessError
from trackfolio.domain.catalog import CatalogEntry, CatalogSummary
from trackfolio.domain.catalog_edit import (
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
    """Fallo recuperable de edición, con mensaje apto para cualquier interfaz."""

    def __init__(self, message: str, *, backup_path: Path | None = None) -> None:
        self.backup_path = backup_path
        super().__init__(message)


class CatalogEditConflict(CatalogEditError):
    """El registro o sus relaciones cambiaron desde que se preparó el borrador."""


class CatalogRecordMissing(CatalogEditError):
    """El archivo seleccionado ya no existe en el catálogo."""


class CatalogEditValidationError(CatalogEditError):
    def __init__(self, errors: tuple[FieldError, ...]) -> None:
        self.errors = errors
        super().__init__("Revisa los campos indicados antes de guardar.")


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
    """Normalizar sólo lo solicitado, manteniendo ausente y borrado como casos distintos."""
    errors: list[FieldError] = []
    normalized: dict[EditField, EditValue] = {}
    previous = values.as_dict()
    seen: set[EditField] = set()
    for change in patch.changes:
        field, value = change.field, change.value
        if field not in EDIT_FIELDS:
            raise CatalogEditError("El cambio contiene un campo que no se puede editar.")
        if field in seen:
            errors.append(FieldError(field, "El campo aparece más de una vez en la solicitud."))
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
                    errors.append(FieldError(field, "Introduce un entero positivo o deja vacío."))
                    continue
            maximum = 9999 if field == "album_year" else 2**63 - 1
            if value is not None and (type(value) is not int or not 1 <= value <= maximum):
                message = (
                    "Introduce un año entre 1 y 9999 o deja vacío."
                    if field == "album_year"
                    else "Introduce un entero positivo dentro del rango admitido por el catálogo."
                )
                errors.append(FieldError(field, message))
                continue
        elif field in ("artists", "genres"):
            if not isinstance(value, tuple) or any(not isinstance(item, str) for item in value):
                errors.append(FieldError(field, "Introduce una lista de nombres completos."))
                continue
            value = tuple(dict.fromkeys(item for item in value if item.strip()))
        else:
            if value is not None and not isinstance(value, str):
                errors.append(FieldError(field, "Introduce texto o deja el campo vacío."))
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
                errors.append(FieldError(number_field, "El número no puede superar su total."))
                errors.append(FieldError(total_field, "El total no puede ser menor que el número."))
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
                exc.add_note(f"No se pudo cerrar el acceso al catálogo: {cleanup}")
            raise
        try:
            session.close()
        except Exception as exc:
            return replace(
                outcome,
                warning=f"Los cambios se guardaron, pero no se pudo cerrar el acceso: {exc}",
            )
        return outcome
