"""Pure Python import orchestration: no Qt, Mutagen, ORM, or database needed."""

from dataclasses import FrozenInstanceError

import pytest

from trackfolio.application.catalog import (
    ImportAudio,
    MetadataReadError,
    prepare_audio_source,
    validate_library_root,
)
from trackfolio.application.import_catalog import (
    AudioScanError,
    AudioSource,
    ImportCatalog,
    ImportIssue,
    ImportProgress,
    ImportReport,
    ImportRequest,
    ImportTargetError,
    SaveOutcome,
    ScanResult,
)
from trackfolio.domain.metadata import TrackMetadata


class FakeScanner:
    def __init__(self, sources=(), issues=(), completed=True):
        self.sources = tuple(sources)
        self.issues = tuple(issues)
        self.completed = completed
        self.calls = []
        self.error = None
        self.after_discovered = lambda: None

    def scan(self, root, is_cancelled, on_discovered):
        self.calls.append(root)
        if self.error:
            raise self.error
        found = []
        for source in self.sources:
            if is_cancelled():
                return ScanResult(tuple(found), self.issues, False)
            found.append(source)
            on_discovered(len(found))
            self.after_discovered()
        return ScanResult(tuple(found), self.issues, self.completed)


class FakeTarget:
    def __init__(self, operations=()):
        self.operations = iter(operations)
        self.writes = []
        self.events = []
        self.write_error = None
        self.fail_after = 0
        self.close_error = None
        self.discard_error = None
        self.after_write = lambda: None

    def write(self, metadata, library_root, relative_path):
        if self.write_error and len(self.writes) >= self.fail_after:
            raise self.write_error
        self.writes.append((metadata, library_root, relative_path))
        self.events.append("write")
        self.after_write()
        return SaveOutcome(len(self.writes), len(self.writes), next(self.operations, "created"))

    def close(self):
        self.events.append("close")
        if self.close_error:
            raise self.close_error

    def discard(self):
        assert "close" in self.events
        self.events.append("discard")
        if self.discard_error:
            raise self.discard_error


class FakeFactory:
    def __init__(self, target):
        self.target = target
        self.validations = []
        self.openings = []
        self.validate_error = None
        self.open_error = None
        self.after_open = lambda: None

    def validate(self, database_path, mode):
        self.validations.append((database_path, mode))
        if self.validate_error:
            raise self.validate_error
        return database_path.resolve()

    def open(self, database_path, mode):
        self.openings.append((database_path, mode))
        if self.open_error:
            raise self.open_error
        self.after_open()
        return self.target


def setup_import(tmp_path, filenames=("Álbum/a.flac", "b.MP3"), operations=()):
    root = tmp_path / "Música con espacios"
    root.mkdir()
    sources = []
    for filename in filenames:
        path = root / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"fake reader supplies metadata")
        sources.append(AudioSource(path, filename))
    scanner = FakeScanner(sources)
    target = FakeTarget(operations)
    factory = FakeFactory(target)
    request = ImportRequest(root, tmp_path / "catalog.tfo", "create")
    return request, scanner, target, factory


def test_committed_operations_and_scan_issues_are_counted_separately(tmp_path):
    request, scanner, target, factory = setup_import(tmp_path, operations=("updated", "created"))
    scanner.issues = (ImportIssue(request.library_root / "private", "scan", "Sin acceso"),)
    events = []
    report = ImportCatalog(scanner, lambda _: TrackMetadata(audio_format="flac"), factory).execute(
        request, on_progress=events.append
    )

    assert (report.state, report.created, report.updated, report.failed) == ("completed", 1, 1, 0)
    assert (report.discovered, report.total, report.processed, report.saved, report.pending) == (
        2,
        2,
        2,
        2,
        0,
    )
    assert report.issues == scanner.issues
    assert target.events == ["write", "write", "close"]
    assert [write[2] for write in target.writes] == ["Álbum/a.flac", "b.MP3"]
    assert all(write[1] == request.library_root.resolve() for write in target.writes)
    assert [event.processed for event in events] == sorted(event.processed for event in events)
    assert events[0].phase == "preparing"
    assert events[-1].phase == "finalizing"
    assert all(event.total is None for event in events if event.phase == "scanning")
    assert events[-1].saved == 2


@pytest.mark.parametrize("failure", [MetadataReadError("Audio corrupto"), OSError("Desaparecido")])
def test_read_failure_is_individual_and_open_is_deferred_until_valid_metadata(tmp_path, failure):
    request, scanner, target, factory = setup_import(tmp_path)
    reads = []

    def read(path):
        reads.append(path)
        if len(reads) == 1:
            assert factory.openings == []
            raise failure
        assert factory.openings == []
        return TrackMetadata(audio_format="mp3")

    report = ImportCatalog(scanner, read, factory).execute(request)
    assert (report.state, report.created, report.failed, report.pending) == ("completed", 1, 1, 0)
    assert report.issues == (ImportIssue(reads[0], "read", str(failure)),)
    assert len(factory.openings) == len(target.writes) == 1
    assert target.events == ["write", "close"]


@pytest.mark.parametrize("filenames", [(), ("invalid.flac",)])
def test_empty_or_unreadable_library_never_creates_catalog(tmp_path, filenames):
    request, scanner, target, factory = setup_import(tmp_path, filenames)

    def read(_):
        raise MetadataReadError("Archivo corrupto")

    report = ImportCatalog(scanner, read, factory).execute(request)
    assert (report.state, report.saved, report.failed) == ("completed", 0, len(filenames))
    assert factory.openings == target.events == []
    assert not request.database_path.exists()


def test_initial_cancellation_skips_validation_and_scan(tmp_path):
    request, scanner, target, factory = setup_import(tmp_path)
    report = ImportCatalog(scanner, lambda _: pytest.fail("reader"), factory).execute(
        request, is_cancelled=lambda: True
    )
    assert (report.state, report.total, report.pending, report.processed) == (
        "cancelled",
        None,
        None,
        0,
    )
    assert factory.validations == scanner.calls == target.events == []


def test_cancelled_scan_keeps_discovered_count_and_unknown_total(tmp_path):
    request, scanner, target, factory = setup_import(tmp_path)
    cancelled = False

    def cancel():
        nonlocal cancelled
        cancelled = True

    scanner.after_discovered = cancel
    report = ImportCatalog(scanner, lambda _: pytest.fail("reader"), factory).execute(
        request, is_cancelled=lambda: cancelled
    )
    assert (report.state, report.discovered, report.total, report.pending) == (
        "cancelled",
        1,
        None,
        None,
    )
    assert factory.openings == target.events == []


def test_scan_incompletion_does_not_import_partial_candidates(tmp_path):
    request, scanner, target, factory = setup_import(tmp_path)
    scanner.completed = False
    report = ImportCatalog(scanner, lambda _: pytest.fail("reader"), factory).execute(request)
    assert (report.state, report.discovered, report.total, report.saved) == (
        "cancelled",
        2,
        None,
        0,
    )
    assert factory.openings == target.events == []


def test_cancel_after_read_does_not_open_destination(tmp_path):
    request, scanner, target, factory = setup_import(tmp_path)
    cancelled = False

    def read(_):
        nonlocal cancelled
        cancelled = True
        return TrackMetadata()

    report = ImportCatalog(scanner, read, factory).execute(request, lambda: cancelled)
    assert (report.state, report.processed, report.pending) == ("cancelled", 0, 2)
    assert factory.openings == target.events == []


def test_cancel_from_current_file_progress_is_observed_before_read(tmp_path):
    request, scanner, target, factory = setup_import(tmp_path)
    cancelled = False

    def progress(event):
        nonlocal cancelled
        if event.current_path is not None:
            cancelled = True

    report = ImportCatalog(scanner, lambda _: pytest.fail("reader"), factory).execute(
        request, lambda: cancelled, progress
    )
    assert (report.state, report.saved, report.pending) == ("cancelled", 0, 2)
    assert factory.openings == target.events == []


def test_cancel_after_open_closes_and_discards_only_empty_target(tmp_path):
    request, scanner, target, factory = setup_import(tmp_path)
    cancelled = False

    def cancel():
        nonlocal cancelled
        cancelled = True

    factory.after_open = cancel
    report = ImportCatalog(scanner, lambda _: TrackMetadata(), factory).execute(
        request, lambda: cancelled
    )
    assert (report.state, report.saved, report.pending) == ("cancelled", 0, 2)
    assert target.events == ["close", "discard"]


def test_cancel_after_commit_preserves_partial_result_and_closes_target(tmp_path):
    request, scanner, target, factory = setup_import(tmp_path)
    cancelled = False

    def cancel():
        nonlocal cancelled
        cancelled = True

    target.after_write = cancel
    report = ImportCatalog(scanner, lambda _: TrackMetadata(), factory).execute(
        request, lambda: cancelled
    )
    assert (report.state, report.created, report.failed, report.pending) == ("cancelled", 1, 0, 1)
    assert target.events == ["write", "close"]


def test_validation_failures_do_not_scan_or_open(tmp_path):
    request, scanner, target, factory = setup_import(tmp_path)
    factory.validate_error = ImportTargetError("El destino ya existe")
    report = ImportCatalog(scanner, lambda _: pytest.fail("reader"), factory).execute(request)
    assert (report.state, report.total, report.fatal_error) == (
        "failed",
        None,
        "El destino ya existe",
    )
    assert scanner.calls == factory.openings == target.events == []


def test_invalid_root_fails_before_destination_validation(tmp_path):
    request, scanner, target, factory = setup_import(tmp_path)
    request = ImportRequest(tmp_path / "missing", request.database_path, "create")
    report = ImportCatalog(scanner, lambda _: pytest.fail("reader"), factory).execute(request)
    assert report.state == "failed"
    assert report.fatal_error
    assert factory.validations == scanner.calls == target.events == []


def test_fatal_scan_error_does_not_prepare_writer(tmp_path):
    request, scanner, target, factory = setup_import(tmp_path)
    scanner.error = AudioScanError("No se puede explorar la raíz")
    report = ImportCatalog(scanner, lambda _: pytest.fail("reader"), factory).execute(request)
    assert (report.state, report.total, report.fatal_error) == (
        "failed",
        None,
        "No se puede explorar la raíz",
    )
    assert factory.openings == target.events == []


def test_open_failure_keeps_current_candidate_pending_and_reports_cleanup(tmp_path):
    request, scanner, target, factory = setup_import(tmp_path)
    cleanup = ImportIssue(request.database_path, "cleanup", "No se pudo eliminar el archivo nuevo")
    factory.open_error = ImportTargetError("No se pudo preparar el esquema", cleanup)
    report = ImportCatalog(scanner, lambda _: TrackMetadata(), factory).execute(request)
    assert (report.state, report.saved, report.failed, report.pending) == ("failed", 0, 0, 2)
    assert report.issues == (cleanup,)
    assert report.fatal_error == "No se pudo preparar el esquema"
    assert target.events == []


@pytest.mark.parametrize("committed", [0, 1])
def test_write_failure_stops_batch_counts_failed_and_preserves_commits(tmp_path, committed):
    request, scanner, target, factory = setup_import(tmp_path, ("a.flac", "b.flac", "c.mp3"))
    target.write_error = ImportTargetError("El destino está bloqueado")
    target.fail_after = committed
    report = ImportCatalog(scanner, lambda _: TrackMetadata(), factory).execute(request)
    assert (report.state, report.created, report.failed, report.pending) == (
        "failed",
        committed,
        1,
        2 - committed,
    )
    assert report.fatal_error == "El destino está bloqueado"
    assert report.issues[-1].stage == "write"
    assert target.events == ["write"] * committed + ["close"] + (
        ["discard"] if not committed else []
    )


def test_cleanup_failure_is_reported_without_losing_cancellation_or_counts(tmp_path):
    request, scanner, target, factory = setup_import(tmp_path)
    cancelled = False

    def cancel():
        nonlocal cancelled
        cancelled = True

    factory.after_open = cancel
    target.discard_error = ImportTargetError("Permanece el catálogo vacío")
    report = ImportCatalog(scanner, lambda _: TrackMetadata(), factory).execute(
        request, lambda: cancelled
    )
    assert (report.state, report.saved, report.failed, report.pending) == ("cancelled", 0, 0, 2)
    assert report.issues == (
        ImportIssue(request.database_path, "cleanup", "Permanece el catálogo vacío"),
    )
    assert target.events == ["close", "discard"]


def test_close_failure_is_fatal_and_retains_saved_counts(tmp_path):
    request, scanner, target, factory = setup_import(tmp_path)
    target.close_error = ImportTargetError("No se pudo cerrar el destino")
    report = ImportCatalog(scanner, lambda _: TrackMetadata(), factory).execute(request)
    assert (report.state, report.saved, report.pending) == ("failed", 2, 0)
    assert report.fatal_error == "No se pudo cerrar el destino"
    assert report.issues == (
        ImportIssue(request.database_path, "cleanup", "No se pudo cerrar el destino"),
    )
    assert target.events == ["write", "write", "close"]


def test_unexpected_progress_failure_still_closes_writer(tmp_path):
    request, scanner, target, factory = setup_import(tmp_path)

    def progress(event):
        if event.phase == "finalizing":
            raise RuntimeError("The calling observer failed")

    with pytest.raises(RuntimeError, match="observer"):
        ImportCatalog(scanner, lambda _: TrackMetadata(), factory).execute(
            request, on_progress=progress
        )
    assert target.events == ["write", "write", "close"]


def test_file_removed_after_scan_is_individual_failure_without_reader_call(tmp_path):
    request, scanner, target, factory = setup_import(tmp_path, ("missing.flac",))
    scanner.sources[0].path.unlink()
    report = ImportCatalog(scanner, lambda _: pytest.fail("reader"), factory).execute(request)
    assert (report.state, report.failed, report.pending) == ("completed", 1, 0)
    assert report.issues[0].stage == "read"
    assert factory.openings == target.events == []


@pytest.mark.parametrize("inside_root", [False, True])
def test_link_inserted_after_scan_is_rejected_before_reading(tmp_path, inside_root):
    request, scanner, target, factory = setup_import(tmp_path, ("candidate.flac",))
    destination = (request.library_root if inside_root else tmp_path) / "actual.flac"
    destination.touch()
    candidate = scanner.sources[0].path
    candidate.unlink()
    try:
        candidate.symlink_to(destination)
    except (OSError, NotImplementedError):
        pytest.skip("Creating symbolic links is unavailable on this platform")
    report = ImportCatalog(scanner, lambda _: pytest.fail("reader"), factory).execute(request)
    assert (report.state, report.failed, report.saved) == ("completed", 1, 0)
    assert report.issues[0].stage == "read"
    assert factory.openings == target.events == []


def test_shared_preparation_rejects_directory_and_parent_link(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    real = root / "real"
    real.mkdir()
    (real / "audio.flac").touch()
    with pytest.raises(ValueError, match="regular"):
        prepare_audio_source(real, root)
    alias = root / "alias"
    try:
        alias.symlink_to(real, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("Creating symbolic links is unavailable on this platform")
    with pytest.raises(ValueError, match="enlaces"):
        prepare_audio_source(alias / "audio.flac", root)


def test_shared_validation_and_individual_import_remain_core_only(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    source = root / "audio.flac"
    source.touch()
    assert validate_library_root(root / ".") == root.resolve()
    assert prepare_audio_source(source, root.resolve()) == (source.resolve(), "audio.flac")
    with pytest.raises(ValueError, match="directorio"):
        validate_library_root(source)
    calls = []

    class Repository:
        def save(self, metadata, library_root, relative_path):
            calls.append((metadata, library_root, relative_path))
            return "individual-public-result"

    metadata = TrackMetadata(audio_format="flac")
    result = ImportAudio(lambda _: metadata, Repository()).execute(source)
    assert result == "individual-public-result"
    assert calls == [(metadata, root.resolve(), "audio.flac")]


def test_import_values_are_immutable_and_derived_counts_are_consistent(tmp_path):
    report = ImportReport(tmp_path / "catalog.tfo", "completed", 7, 7, 2, 3, 1, ())
    assert (report.processed, report.saved, report.pending) == (6, 5, 1)
    progress = ImportProgress("importing", 7, 7, 2, 3, 1)
    assert (progress.processed, progress.saved) == (6, 5)
    with pytest.raises(FrozenInstanceError):
        report.created = 99
