"""Importación real con SQLite y contenedores de audio sintéticos temporales."""

import sqlite3
from dataclasses import replace
from pathlib import Path

import pytest
from sqlalchemy import event
from test_metadata import png, write_flac, write_mp3

from trackfolio.application.import_catalog import (
    ImportCatalog,
    ImportRequest,
    ImportTargetError,
)
from trackfolio.domain.metadata import Artwork, RawTagValue, TrackMetadata
from trackfolio.infrastructure import import_target
from trackfolio.infrastructure.audio_scan import FileSystemAudioScanner
from trackfolio.infrastructure.catalog import SqliteCatalogRepository
from trackfolio.infrastructure.database import create_engine, migrate_database
from trackfolio.infrastructure.import_target import SqliteImportTargetFactory
from trackfolio.infrastructure.metadata import read_metadata
from trackfolio.infrastructure.session import open_catalog


@pytest.fixture
def factory():
    return SqliteImportTargetFactory()


def test_validate_create_does_not_create_parent_and_rejects_existing_paths(factory, tmp_path):
    destination = tmp_path / "new folder" / "catálogo % ?.tfo"
    assert factory.validate(destination, "create") == destination
    assert not destination.parent.exists()
    existing = tmp_path / "already.tfo"
    existing.write_bytes(b"preserved")
    with pytest.raises(ImportTargetError, match="ya existe"):
        factory.validate(existing, "create")
    assert existing.read_bytes() == b"preserved"
    existing_directory = tmp_path / "directory"
    existing_directory.mkdir()
    with pytest.raises(ImportTargetError):
        factory.validate(existing_directory / "missing-parent" / "dest.tfo", "bogus")
    existing_file = tmp_path / "parent-file"
    existing_file.touch()
    with pytest.raises(ImportTargetError, match="directorio"):
        factory.validate(existing_file / "dest.tfo", "create")


def test_creation_rejects_dangling_symlink(factory, tmp_path):
    destination = tmp_path / "link.tfo"
    try:
        destination.symlink_to(tmp_path / "missing.tfo")
    except OSError:
        pytest.skip("Symbolic links require privileges on this platform")
    with pytest.raises(ImportTargetError, match="ya existe"):
        factory.open(destination, "create")
    assert destination.is_symlink()
    assert not (tmp_path / "missing.tfo").exists()


@pytest.mark.parametrize("kind", ["missing", "empty", "foreign", "revision", "column", "view"])
def test_update_requires_recognized_strict_catalog(factory, tmp_path, kind):
    destination = tmp_path / f"{kind}.tfo"
    if kind == "empty":
        destination.touch()
    elif kind == "foreign":
        with sqlite3.connect(destination) as connection:
            connection.execute("CREATE TABLE personal_data (name TEXT)")
    elif kind != "missing":
        migrate_database(destination)
        with sqlite3.connect(destination) as connection:
            if kind == "revision":
                connection.execute("UPDATE alembic_version SET version_num = 'future'")
            elif kind == "column":
                connection.execute("ALTER TABLE tracks ADD COLUMN unexpected TEXT")
            else:
                connection.execute("DROP VIEW track_details")
                connection.execute("CREATE VIEW track_details AS SELECT id FROM tracks")
    before = destination.read_bytes() if destination.exists() else None
    with pytest.raises(ImportTargetError):
        factory.validate(destination, "update")
    assert (destination.read_bytes() if destination.exists() else None) == before


def test_writer_reports_commits_without_fetching_detail_and_clears_removed_metadata(
    factory, tmp_path, monkeypatch
):
    destination = tmp_path / "new.tfo"
    target = factory.open(destination, "create")
    metadata = TrackMetadata(
        title="Before",
        artists=("Artist",),
        genres=("Genre",),
        raw_tags=(RawTagValue("TITLE", "Before", 0),),
        artwork=Artwork(png(), "image/png"),
        audio_format="flac",
    )
    statements = []

    def no_get(*_):
        pytest.fail("The writer must not reread committed detail or cover BLOBs")

    def capture(_connection, _cursor, statement, _parameters, _context, _executemany):
        statements.append(statement.lower())

    monkeypatch.setattr(SqliteCatalogRepository, "get", no_get)
    event.listen(target._engine, "before_cursor_execute", capture)
    try:
        first = target.write(metadata, tmp_path, "Album/song.flac")
        second = target.write(TrackMetadata(audio_format="flac"), tmp_path, "Album/song.flac")
        assert first.operation == "created" and second.operation == "updated"
        assert (first.file_id, first.track_id) == (second.file_id, second.track_id)
        assert all("artworks.data" not in statement for statement in statements)
    finally:
        target.close()
    # The confirmed catalogue must never be discarded, even if the caller errs.
    target.discard()
    assert destination.exists()
    monkeypatch.undo()
    session = open_catalog(destination)
    try:
        assert session.get(first.file_id).metadata == TrackMetadata(audio_format="flac")
        assert len(session.list_summaries()) == 1
    finally:
        session.close()


def test_failed_file_rolls_back_and_preserves_previous_commit(factory, tmp_path):
    destination = tmp_path / "rollback.tfo"
    target = factory.open(destination, "create")
    before = TrackMetadata(title="Before", artists=("Keep",), audio_format="mp3")
    first = target.write(before, tmp_path, "song.mp3")
    with pytest.raises(ImportTargetError, match="guardar"):
        target.write(
            replace(before, title="After", album="rollback", track_number=0), tmp_path, "song.mp3"
        )
    target.close()
    session = open_catalog(destination)
    try:
        assert session.get(first.file_id).metadata == before
    finally:
        session.close()
    with sqlite3.connect(destination) as connection:
        assert connection.execute("SELECT count(*) FROM albums").fetchone() == (0,)


def test_discard_removes_only_owned_uncommitted_file(factory, tmp_path):
    destination = tmp_path / "new.tfo"
    target = factory.open(destination, "create")
    target.close()
    target.discard()
    assert not destination.exists()
    target.discard()
    migrate_database(destination)
    target = factory.open(destination, "update")
    target.discard()
    assert destination.exists()


def test_discard_does_not_remove_replacement_at_owned_path(factory, tmp_path):
    destination = tmp_path / "replaced.tfo"
    target = factory.open(destination, "create")
    target.close()
    destination.rename(tmp_path / "original.tfo")
    destination.write_bytes(b"external replacement")
    with pytest.raises(ImportTargetError, match="cambió"):
        target.discard()
    assert destination.read_bytes() == b"external replacement"


def test_exclusive_creation_race_never_adopts_or_deletes_foreign_file(
    factory, tmp_path, monkeypatch
):
    destination = tmp_path / "race.tfo"
    original_open = import_target.os.open

    def competing_open(path, flags, permissions):
        Path(path).write_bytes(b"created by another application")
        return original_open(path, flags, permissions)

    monkeypatch.setattr(import_target.os, "open", competing_open)
    with pytest.raises(ImportTargetError):
        factory.open(destination, "create")
    assert destination.read_bytes() == b"created by another application"


def test_missing_update_between_validation_and_open_is_not_recreated(
    factory, tmp_path, monkeypatch
):
    destination = tmp_path / "disappeared.tfo"
    migrate_database(destination)
    original_validate = factory.validate

    def disappeared(path, mode):
        result = original_validate(path, mode)
        destination.unlink()
        return result

    monkeypatch.setattr(factory, "validate", disappeared)
    with pytest.raises(ImportTargetError):
        factory.open(destination, "update")
    assert not destination.exists()


def test_open_failure_cleans_reserved_file_and_reports_cleanup_failure(
    factory, tmp_path, monkeypatch
):
    destination = tmp_path / "failed.tfo"

    def fail_upgrade(*_):
        raise RuntimeError("simulated migration error")

    monkeypatch.setattr(import_target.command, "upgrade", fail_upgrade)
    with pytest.raises(ImportTargetError) as captured:
        factory.open(destination, "create")
    assert captured.value.cleanup_issue is None
    assert not destination.exists()

    original_unlink = Path.unlink

    def deny_cleanup(path, *args, **kwargs):
        if path == destination:
            raise PermissionError("denied")
        return original_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", deny_cleanup)
    with pytest.raises(ImportTargetError) as captured:
        factory.open(destination, "create")
    assert captured.value.cleanup_issue.path == destination
    assert captured.value.cleanup_issue.stage == "cleanup"
    assert destination.exists()


def test_prevalidation_rejects_readonly_existing_catalog(factory, tmp_path):
    destination = tmp_path / "read-only.tfo"
    migrate_database(destination)
    destination.chmod(0o444)
    try:
        with pytest.raises(ImportTargetError, match="permiso"):
            factory.validate(destination, "update")
    finally:
        destination.chmod(0o600)


def test_storage_lock_is_bounded_and_translated(factory, tmp_path):
    destination = tmp_path / "locked.tfo"
    migrate_database(destination)
    target = factory.open(destination, "update")
    connection = sqlite3.connect(destination)
    try:
        connection.execute("BEGIN IMMEDIATE")
        with pytest.raises(ImportTargetError, match="ocupado"):
            target.write(TrackMetadata(audio_format="mp3"), tmp_path, "song.mp3")
    finally:
        connection.rollback()
        connection.close()
        target.close()
    session = open_catalog(destination)
    try:
        assert session.list_summaries() == ()
    finally:
        session.close()


def test_readonly_sqlite_writer_error_is_translated_and_rolls_back(factory, tmp_path, monkeypatch):
    destination = tmp_path / "readonly-engine.tfo"
    migrate_database(destination)
    session = open_catalog(destination)
    monkeypatch.setattr(import_target, "_writable_engine", lambda _: session._engine)
    target = factory.open(destination, "update")
    try:
        with pytest.raises(ImportTargetError, match="permiso"):
            target.write(TrackMetadata(audio_format="flac"), tmp_path, "track.flac")
        assert session.list_summaries() == ()
    finally:
        target.close()
        session.close()


def test_complete_real_import_reports_corrupt_audio_and_reimport_preserves_ids(factory, tmp_path):
    library = tmp_path / "Música"
    library.mkdir()
    (library / "a corrupt.MP3").write_bytes(b"not audio")
    flac = write_flac(library / "b song.FLAC", [("TITLE", "Title")], [(3, png())])
    write_mp3(library / "c song.mp3")
    destination = tmp_path / "actual.tfo"
    importer = ImportCatalog(FileSystemAudioScanner(), read_metadata, factory)
    report = importer.execute(ImportRequest(library, destination, "create"))
    assert report.state == "completed"
    assert (report.created, report.updated, report.failed, report.pending) == (2, 0, 1, 0)
    assert len(report.issues) == 1 and report.issues[0].stage == "read"
    session = open_catalog(destination)
    try:
        before = session.list_summaries()
        cover = session.get(before[0].file_id).metadata.artwork.data
    finally:
        session.close()
    write_flac(flac)
    report = importer.execute(ImportRequest(library, destination, "update"))
    assert (report.created, report.updated, report.failed) == (0, 2, 1)
    flac.unlink()
    session = open_catalog(destination)
    try:
        after = session.list_summaries()
        assert [(row.file_id, row.track_id) for row in before] == [
            (row.file_id, row.track_id) for row in after
        ]
        assert after[0].title is None
        assert session.get(after[0].file_id).metadata.artwork is None
        assert cover == png()
    finally:
        session.close()


@pytest.mark.parametrize("kind", ["empty", "invalid", "outside-root"])
def test_no_valid_audio_or_invalid_root_does_not_create_catalog(factory, tmp_path, kind):
    library = tmp_path / "library"
    library.mkdir()
    destination = tmp_path / "untouched" / "dest.tfo"
    if kind == "invalid":
        (library / "bad.mp3").write_bytes(b"bad")
    elif kind == "outside-root":
        library = tmp_path / "missing"
    importer = ImportCatalog(FileSystemAudioScanner(), read_metadata, factory)
    report = importer.execute(ImportRequest(library, destination, "create"))
    assert report.saved == 0
    assert not destination.exists() and not destination.parent.exists()


def test_legacy_script_rejects_outside_root_before_migration(tmp_path, capsys):
    from conftest import load_script

    script = load_script("import_audio")
    outside = write_mp3(tmp_path / "outside.mp3")
    library = tmp_path / "library"
    library.mkdir()
    destination = tmp_path / "new-directory" / "single.tfo"
    assert (
        script.main([str(outside), "--library-root", str(library), "--database", str(destination)])
        == 1
    )
    assert "dentro" in capsys.readouterr().out
    assert not destination.exists() and not destination.parent.exists()


def test_legacy_script_keeps_arguments_and_imports_actual_audio(tmp_path, capsys):
    from conftest import load_script

    script = load_script("import_audio")
    source = write_mp3(tmp_path / "single.mp3")
    destination = tmp_path / "single.tfo"
    assert script.main([str(source), "--database", str(destination)]) == 0
    output = capsys.readouterr().out
    assert "file_id=1, track_id=1" in output and "track_details" in output
    engine = create_engine(destination)
    try:
        assert len(SqliteCatalogRepository(engine).list_summaries()) == 1
    finally:
        engine.dispose()


def test_legacy_script_uses_shared_link_validation_before_creating_catalog(tmp_path, capsys):
    from conftest import load_script

    script = load_script("import_audio")
    source = write_mp3(tmp_path / "original.mp3")
    link = tmp_path / "alias.mp3"
    try:
        link.symlink_to(source)
    except OSError:
        pytest.skip("Symbolic links require privileges on this platform")
    destination = tmp_path / "not-created.tfo"
    assert script.main([str(link), "--database", str(destination)]) == 1
    assert "enlaces" in capsys.readouterr().out
    assert not destination.exists()
