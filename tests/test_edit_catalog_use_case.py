"""A session cleanup failure must preserve the confirmed write or its original error."""

from dataclasses import replace

import pytest

from trackfolio.application.edit_catalog import (
    CatalogEditConflict,
    CatalogEditOutcome,
    UpdateCatalogTrack,
)
from trackfolio.domain.catalog import CatalogEntry, CatalogSummary
from trackfolio.domain.catalog_edit import (
    EditableTrack,
    EditableValues,
    FieldChange,
    TrackEditPatch,
)
from trackfolio.domain.metadata import TrackMetadata


class FailingCleanupSession:
    def __init__(self, path, *, apply_error=None):
        self.database_path = path
        self.backup_path = path.with_suffix(".bak")
        self.apply_error = apply_error
        self.applied = []
        self.close_calls = 0
        self.outcome = CatalogEditOutcome(
            CatalogEntry(1, 2, path.parent / "music", "01.flac", TrackMetadata(title="Corrected")),
            CatalogSummary(1, 2, "Corrected", (), None, None, "01.flac"),
            self.backup_path,
        )

    def apply_edit(self, original, patch):
        self.applied.append((original, patch))
        if self.apply_error is not None:
            raise self.apply_error
        return self.outcome

    def close(self):
        self.close_calls += 1
        raise RuntimeError("cleanup failed")


class SessionFactory:
    def __init__(self, session):
        self.session = session
        self.opened = []

    def open_writer(self, path):
        self.opened.append(path)
        return self.session


def test_confirmed_edit_survives_cleanup_failure(tmp_path):
    path = tmp_path / "catalogue.tfo"
    session = FailingCleanupSession(path)
    factory = SessionFactory(session)
    original = EditableTrack(1, 2, EditableValues(title="Original"), "snapshot token")
    patch = TrackEditPatch((FieldChange("title", "Corrected"),))

    outcome = UpdateCatalogTrack(factory).execute(path, original, patch)

    assert outcome is not None
    assert outcome.warning is not None
    assert "guardaron" in outcome.warning
    assert "cleanup failed" in outcome.warning
    assert replace(outcome, warning=None) == session.outcome
    assert session.applied == [(original, patch)]
    assert session.close_calls == 1
    assert factory.opened == [path]


def test_edit_conflict_survives_cleanup_failure(tmp_path):
    path = tmp_path / "catalogue.tfo"
    original_error = CatalogEditConflict("The record changed")
    session = FailingCleanupSession(path, apply_error=original_error)
    factory = SessionFactory(session)
    original = EditableTrack(1, 2, EditableValues(title="Original"), "snapshot token")
    patch = TrackEditPatch((FieldChange("title", "Corrected"),))

    with pytest.raises(CatalogEditConflict) as captured:
        UpdateCatalogTrack(factory).execute(path, original, patch)

    assert captured.value is original_error
    assert str(captured.value) == "The record changed"
    assert captured.value.backup_path == session.backup_path
    assert any("cleanup failed" in note for note in captured.value.__notes__)
    assert session.applied == [(original, patch)]
    assert session.close_calls == 1
    assert factory.opened == [path]
