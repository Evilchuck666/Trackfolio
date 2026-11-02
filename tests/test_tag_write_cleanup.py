"""Successful batches remove backup roots; incomplete batches retain recovery copies."""

import json

import pytest
from test_catalog_edit import edit
from test_tag_write import make_source, prepare_change
from test_tag_write import setup_tags as setup_tags

from trackfolio.application.write_tags import PreviewTagWrites, WriteTagWrites
from trackfolio.domain.tag_write import TagWriteRequest
from trackfolio.infrastructure.metadata import read_metadata
from trackfolio.infrastructure.tag_write_files import FileTagJournal


def batch(setup_tags, tmp_path, *, separate=False):
    database, repository, catalog, codec, files = setup_tags
    sources = [make_source(tmp_path, kind) for kind in ("flac", "mp3")]
    if separate:
        destination = tmp_path / "another album" / "b.mp3"
        destination.parent.mkdir()
        sources[1] = sources[1].rename(destination)
    entries = tuple(
        repository.save(read_metadata(source), tmp_path, str(source.relative_to(tmp_path)))
        for source in sources
    )
    for entry in entries:
        edit(database, entry.file_id, title="Modified")
    preview = PreviewTagWrites(catalog, codec, files).execute(
        TagWriteRequest(database, tuple(entry.file_id for entry in entries), ("title",))
    )
    return sources, entries, preview


@pytest.mark.parametrize("separate", [False, True])
def test_success_removes_whole_backup_roots_after_every_catalogue_confirmation(
    setup_tags, tmp_path, monkeypatch, separate
):
    sources, entries, preview = batch(setup_tags, tmp_path, separate=separate)
    _, repository, catalog, codec, files = setup_tags
    originals = tuple(source.read_bytes() for source in sources)
    roots = {source.parent / ".trackfolio-backups" for source in sources}
    for root in roots:
        old = root / "older-uuid" / "prior.tfo-bak"
        old.parent.mkdir(parents=True)
        old.write_bytes(b"older backup")
    unrelated = tmp_path / "unselected" / ".trackfolio-backups" / "keep.tfo-bak"
    unrelated.parent.mkdir(parents=True)
    unrelated.write_bytes(b"unrelated")
    confirmed, removed = [], []
    confirm, discard = catalog.confirm, files.discard_backups

    def confirm_and_record(*args):
        confirm(*args)
        confirmed.append(args[1].file_id)
        assert all(root.is_dir() for root in roots)

    def discard_after_confirming_every_file(root):
        assert confirmed == [entry.file_id for entry in entries]
        for source, entry, original in zip(sources, entries, originals, strict=True):
            assert read_metadata(source).title == "Modified"
            assert repository.get(entry.file_id).metadata.title == "Modified"
            if source.parent == root.parent:
                backup = root / preview.operation_id / f"{entry.file_id}-{source.name}.tfo-bak"
                assert backup.read_bytes() == original
        discard(root)
        removed.append(root)

    monkeypatch.setattr(catalog, "confirm", confirm_and_record)
    monkeypatch.setattr(files, "discard_backups", discard_after_confirming_every_file)
    report = WriteTagWrites(catalog, codec, files).execute(
        preview, tuple(entry.file_id for entry in entries)
    )
    assert not report.fatal_error and not report.cancelled
    assert [item.state for item in report.results] == ["confirmed", "confirmed"]
    assert all(item.backup_path is None for item in report.results)
    assert set(removed) == roots and len(removed) == len(roots)
    assert all(not root.exists() for root in roots)
    assert unrelated.read_bytes() == b"unrelated"
    journal = json.loads(report.journal_path.read_text())
    assert journal["closed"] is True
    assert all(item["backup_path"] is None for item in journal["report"]["results"])


def test_partial_write_keeps_backups_for_successful_and_failed_files(
    setup_tags, tmp_path, monkeypatch
):
    sources, entries, preview = batch(setup_tags, tmp_path)
    _, _, catalog, codec, files = setup_tags
    originals = tuple(source.read_bytes() for source in sources)
    write = codec.write_verified
    calls = 0

    def fail_second(*args):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("Cannot write second file")
        return write(*args)

    monkeypatch.setattr(codec, "write_verified", fail_second)
    report = WriteTagWrites(catalog, codec, files).execute(
        preview, tuple(entry.file_id for entry in entries)
    )
    assert [item.state for item in report.results] == ["confirmed", "failed"]
    assert (sources[0].parent / ".trackfolio-backups").is_dir()
    for item, original in zip(report.results, originals, strict=True):
        assert item.backup_path.read_bytes() == original


def test_journal_failure_before_cleanup_preserves_backup(setup_tags, tmp_path, monkeypatch):
    source, entry, preview = prepare_change(setup_tags, tmp_path)
    _, _, catalog, codec, files = setup_tags
    original = source.read_bytes()

    def fail_report(*_args):
        raise OSError("Cannot persist completion")

    monkeypatch.setattr(FileTagJournal, "finish", fail_report)
    report = WriteTagWrites(catalog, codec, files).execute(preview, (entry.file_id,))
    assert report.fatal_error and "Cannot persist completion" in report.fatal_error
    assert report.results[0].state == "confirmed"
    assert report.results[0].backup_path.read_bytes() == original
    assert (source.parent / ".trackfolio-backups").is_dir()


def test_cleanup_failure_is_reported_and_preserves_remaining_backup(
    setup_tags, tmp_path, monkeypatch
):
    source, entry, preview = prepare_change(setup_tags, tmp_path)
    _, _, catalog, codec, files = setup_tags
    original = source.read_bytes()

    def denied(_directory):
        raise PermissionError("Backup directory is locked")

    monkeypatch.setattr(files, "discard_backups", denied)
    report = WriteTagWrites(catalog, codec, files).execute(preview, (entry.file_id,))
    assert report.results[0].state == "confirmed"
    assert report.fatal_error and "Backup directory is locked" in report.fatal_error
    assert report.results[0].backup_path.read_bytes() == original
    assert (source.parent / ".trackfolio-backups").is_dir()
    assert json.loads(report.journal_path.read_text())["closed"] is False


@pytest.mark.parametrize("replacement", ["directory", "symlink"])
def test_replaced_backup_root_is_not_deleted(setup_tags, tmp_path, monkeypatch, replacement):
    source, entry, preview = prepare_change(setup_tags, tmp_path)
    _, _, catalog, codec, files = setup_tags
    original = source.read_bytes()
    moved = source.parent / "moved-backups"
    unrelated = tmp_path / "unrelated"
    unrelated.mkdir()
    (unrelated / "keep.txt").write_text("keep")
    discard = files.discard_backups

    def replace_root(root):
        root.rename(moved)
        if replacement == "symlink":
            try:
                root.symlink_to(unrelated, target_is_directory=True)
            except OSError:
                pytest.skip("Creating directory symlinks is not permitted")
        else:
            root.mkdir()
            (root / "keep.txt").write_text("keep")
        discard(root)

    monkeypatch.setattr(files, "discard_backups", replace_root)
    report = WriteTagWrites(catalog, codec, files).execute(preview, (entry.file_id,))
    assert report.fatal_error
    assert (unrelated / "keep.txt").read_text() == "keep"
    assert (source.parent / ".trackfolio-backups" / "keep.txt").read_text() == "keep"
    assert next(moved.rglob("*.tfo-bak")).read_bytes() == original


def test_failure_after_cleaning_one_folder_keeps_remaining_report_paths(
    setup_tags, tmp_path, monkeypatch
):
    sources, entries, preview = batch(setup_tags, tmp_path, separate=True)
    _, _, catalog, codec, files = setup_tags
    discard = files.discard_backups
    calls = 0

    def fail_second(root):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("Cannot clean another folder")
        discard(root)

    monkeypatch.setattr(files, "discard_backups", fail_second)
    report = WriteTagWrites(catalog, codec, files).execute(
        preview, tuple(entry.file_id for entry in entries)
    )
    assert report.fatal_error
    assert sum(item.backup_path is None for item in report.results) == 1
    for item in report.results:
        root = item.path.parent / ".trackfolio-backups"
        if item.backup_path is None:
            assert not root.exists()
        else:
            assert item.backup_path.is_file() and root.is_dir()


def test_retry_can_create_a_new_backup_root_after_the_previous_one_was_moved(
    setup_tags, tmp_path, monkeypatch
):
    source, entry, preview = prepare_change(setup_tags, tmp_path)
    database, _, catalog, codec, files = setup_tags
    write = codec.write_verified

    def failed(*_args):
        raise OSError("First attempt failed")

    monkeypatch.setattr(codec, "write_verified", failed)
    first = WriteTagWrites(catalog, codec, files).execute(preview, (entry.file_id,))
    assert first.results[0].state == "failed"
    root = source.parent / ".trackfolio-backups"
    root.rename(source.parent / "manually-moved-backups")
    monkeypatch.setattr(codec, "write_verified", write)
    preview = PreviewTagWrites(catalog, codec, files).execute(
        TagWriteRequest(database, (entry.file_id,), ("title",))
    )
    report = WriteTagWrites(catalog, codec, files).execute(preview, (entry.file_id,))
    assert report.results[0].state == "confirmed" and not report.fatal_error
    assert report.results[0].backup_path is None and not root.exists()
