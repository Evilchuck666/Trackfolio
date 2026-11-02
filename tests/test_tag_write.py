"""Write real temporary containers through the catalogue and preserve their payload."""

import os
from dataclasses import replace

import pytest
from audio_samples import FLAC as REAL_FLAC
from audio_samples import MP3 as REAL_MP3
from mutagen.flac import FLAC
from mutagen.id3 import APIC, ID3, TALB, TCON, TDRC, TIT2, TPE1, TPOS, TRCK, TXXX, USLT
from test_catalog_edit import edit
from test_metadata import png, write_flac, write_mp3

from trackfolio.application.write_tags import PreviewTagWrites, ReviewTagWrites, WriteTagWrites
from trackfolio.domain.catalog_edit import EDIT_FIELDS
from trackfolio.domain.tag_write import TagWriteRequest
from trackfolio.infrastructure.catalog import SqliteCatalogRepository
from trackfolio.infrastructure.database import create_engine, migrate_database
from trackfolio.infrastructure.metadata import read_metadata
from trackfolio.infrastructure.tag_write import MutagenTagCodec
from trackfolio.infrastructure.tag_write_catalog import SqliteTagCatalog
from trackfolio.infrastructure.tag_write_files import FileTagAccess, FileTagJournal


@pytest.fixture
def setup_tags(tmp_path):
    path = tmp_path / "catalog.tfo"
    migrate_database(path)
    engine = create_engine(path)
    files = FileTagAccess(tmp_path / "operations")
    codec, catalog = MutagenTagCodec(), SqliteTagCatalog()
    try:
        yield path, SqliteCatalogRepository(engine), catalog, codec, files
    finally:
        engine.dispose()


def make_source(tmp_path, kind):
    root = tmp_path / "Música Ω"
    root.mkdir(exist_ok=True)
    if kind == "flac":
        return write_flac(
            root / "a.flac",
            [
                ("TITLE", "Original"),
                ("ARTIST", "Artist"),
                ("ALBUM", "Old album"),
                ("DATE", "2020-02-29"),
                ("TRACKNUMBER", "1/10"),
                ("DISCNUMBER", "1/2"),
                ("GENRE", "Metal"),
                ("LYRICS", "Old lyrics"),
                ("REPLAYGAIN_TRACK_GAIN", "-3 dB"),
            ],
            [(3, png()), (4, png(2, 1))],
        )
    source = write_mp3(root / "a.mp3")
    tags = ID3()
    tags.add(TIT2(encoding=3, text=["Original"]))
    tags.add(TPE1(encoding=3, text=["Artist"]))
    tags.add(TALB(encoding=3, text=["Old album"]))
    tags.add(TDRC(encoding=3, text=["2020-02-29"]))
    tags.add(TRCK(encoding=3, text=["1/10"]))
    tags.add(TPOS(encoding=3, text=["1/2"]))
    tags.add(TCON(encoding=3, text=["Metal"]))
    tags.add(USLT(encoding=3, lang="eng", desc="Original", text="Old lyrics"))
    tags.save(source)
    return source


@pytest.mark.parametrize("kind", ["flac", "mp3"])
def test_write_and_import_into_new_catalogue(setup_tags, tmp_path, kind):
    database, repository, catalog, codec, files = setup_tags
    source = make_source(tmp_path, kind)
    original = source.read_bytes()
    entry = repository.save(read_metadata(source), source.parent, source.name)
    changed = dict(
        title="Corrected",
        artists=("AC/DC", "Artist; two"),
        album="New album",
        album_year=1981,
        track_number=3,
        track_total=12,
        disc_number=2,
        disc_total=3,
        genres=("Rock", "Metal"),
        lyrics="New lyrics\nSecond line",
    )
    edit(database, entry.file_id, **changed)
    request = TagWriteRequest(database, (entry.file_id,), tuple(changed), allow_date_loss=True)
    preview = PreviewTagWrites(catalog, codec, files).execute(request)
    assert preview.items[0].state == "ready", preview.items[0].message
    assert source.read_bytes() == original
    assert not files.journal_root.exists()
    report = WriteTagWrites(catalog, codec, files).execute(preview, (entry.file_id,))
    assert report.results[0].state == "confirmed", report.results[0].message
    assert report.results[0].backup_path.read_bytes() == original
    actual = read_metadata(source)
    for field, value in changed.items():
        assert getattr(actual, field) == value
    other = tmp_path / "new.tfo"
    migrate_database(other)
    engine = create_engine(other)
    try:
        reimported = SqliteCatalogRepository(engine).save(actual, source.parent, source.name)
        for field, value in changed.items():
            assert getattr(reimported.metadata, field) == value
    finally:
        engine.dispose()
    assert files.pending() == ()


def test_only_selected_field_written_other_catalogue_corrections_survive(setup_tags, tmp_path):
    database, repository, catalog, codec, files = setup_tags
    source = make_source(tmp_path, "flac")
    entry = repository.save(read_metadata(source), source.parent, source.name)
    edit(database, entry.file_id, title="Catalog-only", track_number=4, track_total=20)
    preview = PreviewTagWrites(catalog, codec, files).execute(
        TagWriteRequest(database, (entry.file_id,), ("track_number",))
    )
    report = WriteTagWrites(catalog, codec, files).execute(preview, (entry.file_id,))
    assert report.results[0].state == "confirmed", report.results[0].message
    actual = read_metadata(source)
    assert actual.title == "Original" and actual.track_number == 4 and actual.track_total == 10
    metadata = repository.get(entry.file_id).metadata
    assert metadata.title == "Catalog-only" and metadata.track_total == 20


def prepare_change(setup_tags, tmp_path, *, kind="flac", fields=("title",), **changes):
    database, repository, catalog, codec, files = setup_tags
    source = make_source(tmp_path, kind)
    entry = repository.save(read_metadata(source), source.parent, source.name)
    edit(database, entry.file_id, **(changes or {"title": "Corrected"}))
    preview = PreviewTagWrites(catalog, codec, files).execute(
        TagWriteRequest(database, (entry.file_id,), fields, allow_date_loss=True)
    )
    return source, entry, preview


@pytest.mark.parametrize("kind", ["flac", "mp3"])
@pytest.mark.parametrize("field", EDIT_FIELDS)
def test_explicit_clearing_of_each_field(setup_tags, tmp_path, kind, field):
    value = () if field in ("artists", "genres") else None
    source, entry, preview = prepare_change(
        setup_tags, tmp_path, kind=kind, fields=(field,), **{field: value}
    )
    _, _, catalog, codec, files = setup_tags
    if preview.items[0].state == "unchanged":
        assert getattr(read_metadata(source), field) == value
        return
    assert preview.items[0].state == "ready", preview.items[0].message
    report = WriteTagWrites(catalog, codec, files).execute(preview, (entry.file_id,))
    assert report.results[0].state == "confirmed", report.results[0].message
    assert getattr(read_metadata(source), field) == value


@pytest.mark.parametrize("kind", ["flac", "mp3"])
def test_actual_audio_frames_and_unknown_information_preserved(setup_tags, tmp_path, kind):
    database, repository, catalog, codec, files = setup_tags
    source = tmp_path / f"silence.{kind}"
    source.write_bytes(REAL_FLAC if kind == "flac" else REAL_MP3)
    if kind == "flac":
        tags = FLAC(source)
        tags["TITLE"] = ["Before"]
        tags["CUSTOM_KEY"] = ["Unknown value", "Second value"]
        tags.save()
    else:
        tags = ID3()
        tags.add(TIT2(encoding=3, text=["Before"]))
        tags.add(TXXX(encoding=3, desc="CUSTOM_KEY", text=["Unknown value", "Second value"]))
        tags.add(APIC(encoding=3, mime="image/png", type=3, desc="Front", data=png()))
        tags.save(source)
    entry = repository.save(read_metadata(source), tmp_path, source.name)
    before = read_metadata(source)
    edit(database, entry.file_id, title="After")
    preview = PreviewTagWrites(catalog, codec, files).execute(
        TagWriteRequest(database, (entry.file_id,), ("title",))
    )
    report = WriteTagWrites(catalog, codec, files).execute(preview, (entry.file_id,))
    assert report.results[0].state == "confirmed", report.results[0].message
    after = read_metadata(source)
    assert after.title == "After" and after.duration_seconds == before.duration_seconds
    assert after.artwork == before.artwork
    assert tuple(tag.value for tag in after.raw_tags if "custom" in tag.key.lower()) == (
        "Unknown value",
        "Second value",
    )


@pytest.mark.parametrize("change", ["file", "catalogue", "same_stat"])
def test_stale_preview_never_overwrites_changes(setup_tags, tmp_path, change):
    source, entry, preview = prepare_change(setup_tags, tmp_path)
    database, repository, catalog, codec, files = setup_tags
    if change == "catalogue":
        edit(database, entry.file_id, title="Newer correction")
    else:
        info = source.stat()
        payload = bytearray(source.read_bytes())
        payload[-1] ^= 1
        source.write_bytes(payload)
        if change == "same_stat":
            os.utime(source, ns=(info.st_atime_ns, info.st_mtime_ns))
    before = source.read_bytes()
    report = WriteTagWrites(catalog, codec, files).execute(preview, (entry.file_id,))
    assert report.results[0].state == "conflict"
    assert source.read_bytes() == before
    if change == "catalogue":
        assert repository.get(entry.file_id).metadata.title == "Newer correction"


def test_foreign_temporary_is_never_removed(setup_tags, tmp_path):
    source, entry, preview = prepare_change(setup_tags, tmp_path)
    _, _, catalog, codec, files = setup_tags
    temporary = source.parent / f".trackfolio-{preview.operation_id}-{entry.file_id}.tmp"
    temporary.write_bytes(b"foreign file")
    original = source.read_bytes()
    report = WriteTagWrites(catalog, codec, files).execute(preview, (entry.file_id,))
    assert report.results[0].state == "failed"
    assert temporary.read_bytes() == b"foreign file"
    assert source.read_bytes() == original


def test_corrupt_prepared_audio_never_published(setup_tags, tmp_path, monkeypatch):
    source, entry, preview = prepare_change(setup_tags, tmp_path)
    _, _, catalog, codec, files = setup_tags
    original_write = codec._write_flac

    def corrupt(path, plan, fields):
        original_write(path, plan, fields)
        with path.open("ab") as stream:
            stream.write(b"corrupt audio")

    monkeypatch.setattr(codec, "_write_flac", corrupt)
    before = source.read_bytes()
    report = WriteTagWrites(catalog, codec, files).execute(preview, (entry.file_id,))
    assert report.results[0].state == "failed" and "audio" in report.results[0].message
    assert source.read_bytes() == before


def test_write_then_catalogue_failure_reconciles_without_rewriting_audio(
    setup_tags, tmp_path, monkeypatch
):
    source, entry, preview = prepare_change(setup_tags, tmp_path)
    _, _, catalog, codec, files = setup_tags
    confirm = catalog.confirm

    def fail(*args):
        raise OSError("database unavailable")

    monkeypatch.setattr(catalog, "confirm", fail)
    report = WriteTagWrites(catalog, codec, files).execute(preview, (entry.file_id,))
    assert report.results[0].state == "catalog_pending"
    assert len(files.pending()) == 1
    written = source.read_bytes()
    monkeypatch.setattr(catalog, "confirm", confirm)
    review = ReviewTagWrites(catalog, codec, files)
    assert review.execute(report.journal_path).results[0].state == "catalog_pending"
    result = review.execute(report.journal_path, reconcile=True)
    assert result.results[0].state == "confirmed", result.results[0].message
    assert source.read_bytes() == written and files.pending() == ()


@pytest.mark.parametrize(
    "stage", ["backup_verified", "temporary_verified", "publishing", "written", "confirmed"]
)
def test_interruption_at_each_checkpoint_is_reviewable(setup_tags, tmp_path, monkeypatch, stage):
    source, entry, preview = prepare_change(setup_tags, tmp_path)
    _, _, catalog, codec, files = setup_tags
    record = FileTagJournal.record

    def interrupt(self, item, state, **details):
        # An uncatchable interruption models a process exit before persisting this stage.
        if state == stage:
            raise SystemExit("interrupted")
        return record(self, item, state, **details)

    monkeypatch.setattr(FileTagJournal, "record", interrupt)
    with pytest.raises(SystemExit):
        WriteTagWrites(catalog, codec, files).execute(preview, (entry.file_id,))
    monkeypatch.setattr(FileTagJournal, "record", record)
    operations = files.pending()
    assert len(operations) == 1
    report = ReviewTagWrites(catalog, codec, files).execute(
        operations[0].journal_path, reconcile=True
    )
    expected = "confirmed" if stage in ("written", "confirmed") else "pending"
    assert report.results[0].state == expected, report.results[0].message
    assert read_metadata(source).title == ("Corrected" if expected == "confirmed" else "Original")


def test_cancel_after_backup_keeps_original_and_reusable_report(setup_tags, tmp_path):
    source, entry, preview = prepare_change(setup_tags, tmp_path)
    _, _, catalog, codec, files = setup_tags
    before = source.read_bytes()
    cancelled = False

    def progress(value):
        nonlocal cancelled
        if value.phase == "writing":
            cancelled = True

    report = WriteTagWrites(catalog, codec, files).execute(
        preview, (entry.file_id,), is_cancelled=lambda: cancelled, on_progress=progress
    )
    assert report.cancelled and report.results[0].state == "pending"
    assert source.read_bytes() == before
    assert report.results[0].backup_path.read_bytes() == before
    assert not list(source.parent.glob("*.tmp"))


def test_date_precision_requires_explicit_choice(setup_tags, tmp_path):
    source, entry, _ = prepare_change(setup_tags, tmp_path, fields=("album_year",), album_year=1981)
    database, _, catalog, codec, files = setup_tags
    request = TagWriteRequest(database, (entry.file_id,), ("album_year",))
    preview = PreviewTagWrites(catalog, codec, files).execute(request)
    assert preview.items[0].state == "blocked" and "fecha" in preview.items[0].message
    accepted = PreviewTagWrites(catalog, codec, files).execute(
        replace(request, allow_date_loss=True)
    )
    assert accepted.items[0].tags.after_date == "1981"
    report = WriteTagWrites(catalog, codec, files).execute(accepted, (entry.file_id,))
    assert report.results[0].state == "confirmed", report.results[0].message
    assert read_metadata(source).album_date == "1981"


@pytest.mark.parametrize("legacy", ["id3v1", "id3v23_lists"])
def test_legacy_profiles_are_explicitly_blocked(setup_tags, tmp_path, legacy):
    database, repository, catalog, codec, files = setup_tags
    source = make_source(tmp_path, "mp3")
    if legacy == "id3v1":
        with source.open("ab") as stream:
            stream.write(b"TAG" + b"\x00" * 125)
    else:
        tags = ID3(source, translate=False)
        tags.save(source, v2_version=3)
    entry = repository.save(read_metadata(source), source.parent, source.name)
    edit(database, entry.file_id, artists=("One", "Two"))
    original = source.read_bytes()
    preview = PreviewTagWrites(catalog, codec, files).execute(
        TagWriteRequest(database, (entry.file_id,), ("artists",))
    )
    assert preview.items[0].state == "blocked" and "ID3v" in preview.items[0].message
    assert source.read_bytes() == original


def test_lyrics_alias_does_not_override_written_uslt(setup_tags, tmp_path):
    database, repository, catalog, codec, files = setup_tags
    source = make_source(tmp_path, "mp3")
    tags = ID3(source)
    tags.add(TXXX(encoding=3, desc="LYRICS", text=["Alias lyrics"]))
    tags.save(source)
    entry = repository.save(read_metadata(source), source.parent, source.name)
    edit(database, entry.file_id, lyrics="Old lyrics")
    preview = PreviewTagWrites(catalog, codec, files).execute(
        TagWriteRequest(database, (entry.file_id,), ("lyrics",))
    )
    report = WriteTagWrites(catalog, codec, files).execute(preview, (entry.file_id,))
    assert report.results[0].state == "confirmed", report.results[0].message
    assert read_metadata(source).lyrics == "Old lyrics"
    assert "TXXX:LYRICS" not in ID3(source)


@pytest.mark.parametrize("kind", ["flac", "mp3"])
def test_files_without_any_tags_can_be_written(setup_tags, tmp_path, kind):
    database, repository, catalog, codec, files = setup_tags
    source = tmp_path / f"bare.{kind}"
    if kind == "flac":
        write_flac(source)
    else:
        source.write_bytes(REAL_MP3)
    entry = repository.save(read_metadata(source), tmp_path, source.name)
    edit(database, entry.file_id, title="New title")
    preview = PreviewTagWrites(catalog, codec, files).execute(
        TagWriteRequest(database, (entry.file_id,), ("title",))
    )
    report = WriteTagWrites(catalog, codec, files).execute(preview, (entry.file_id,))
    assert report.results[0].state == "confirmed", report.results[0].message
    assert read_metadata(source).title == "New title"


@pytest.mark.parametrize("kind", ["flac", "mp3"])
@pytest.mark.parametrize("year", [1, 9999])
def test_extreme_years_round_trip(setup_tags, tmp_path, kind, year):
    source, entry, preview = prepare_change(
        setup_tags, tmp_path, kind=kind, fields=("album_year",), album_year=year
    )
    _, _, catalog, codec, files = setup_tags
    report = WriteTagWrites(catalog, codec, files).execute(preview, (entry.file_id,))
    assert report.results[0].state == "confirmed", report.results[0].message
    assert read_metadata(source).album_year == year


@pytest.mark.parametrize("kind", ["flac", "mp3"])
def test_compatible_date_precision_is_preserved(setup_tags, tmp_path, kind):
    source, entry, preview = prepare_change(
        setup_tags, tmp_path, kind=kind, fields=("album_year",), album_year=2024
    )
    _, repository, catalog, codec, files = setup_tags
    assert preview.items[0].tags.after_date == "2024-02-29"
    report = WriteTagWrites(catalog, codec, files).execute(preview, (entry.file_id,))
    assert report.results[0].state == "confirmed", report.results[0].message
    assert read_metadata(source).album_date == "2024-02-29"
    assert repository.get(entry.file_id).metadata.album_date == "2024-02-29"


@pytest.mark.parametrize("hazard", ["readonly", "hardlink", "symlink", "missing"])
def test_non_writable_or_aliased_sources_are_blocked(setup_tags, tmp_path, hazard):
    database, repository, catalog, codec, files = setup_tags
    source = make_source(tmp_path, "flac")
    entry = repository.save(read_metadata(source), source.parent, source.name)
    edit(database, entry.file_id, title="Corrected")
    if hazard == "readonly":
        source.chmod(0o444)
    elif hazard == "hardlink":
        os.link(source, source.with_name("other.flac"))
    elif hazard == "symlink":
        target = source.with_name("target.flac")
        source.rename(target)
        try:
            source.symlink_to(target)
        except OSError:
            pytest.skip("Symlinks require additional Windows privileges")
    else:
        source.unlink()
    try:
        preview = PreviewTagWrites(catalog, codec, files).execute(
            TagWriteRequest(database, (entry.file_id,), ("title",))
        )
        assert preview.items[0].state == "blocked"
        assert not files.journal_root.exists()
    finally:
        if hazard == "readonly":
            source.chmod(0o644)


def test_same_file_from_two_library_roots_is_not_written_twice(setup_tags, tmp_path):
    database, repository, catalog, codec, files = setup_tags
    source = make_source(tmp_path, "flac")
    first = repository.save(read_metadata(source), source.parent, source.name)
    second = repository.save(
        read_metadata(source), tmp_path, source.relative_to(tmp_path).as_posix()
    )
    edit(database, first.file_id, title="One")
    edit(database, second.file_id, title="Two")
    preview = PreviewTagWrites(catalog, codec, files).execute(
        TagWriteRequest(database, (first.file_id, second.file_id), ("title",))
    )
    assert [item.state for item in preview.items] == ["conflict", "conflict"]


def test_failure_to_record_publication_does_not_claim_original_is_intact(
    setup_tags, tmp_path, monkeypatch
):
    from trackfolio.application.write_tags import TagJournalError

    source, entry, preview = prepare_change(setup_tags, tmp_path)
    _, _, catalog, codec, files = setup_tags
    record = FileTagJournal.record

    def fail(self, item, state, **details):
        if state == "written":
            raise TagJournalError("journal failure")
        return record(self, item, state, **details)

    monkeypatch.setattr(FileTagJournal, "record", fail)
    report = WriteTagWrites(catalog, codec, files).execute(preview, (entry.file_id,))
    assert report.results[0].state == "catalog_pending" and report.fatal_error
    assert read_metadata(source).title == "Corrected"
    monkeypatch.setattr(FileTagJournal, "record", record)
    recovered = ReviewTagWrites(catalog, codec, files).execute(report.journal_path, reconcile=True)
    assert recovered.results[0].state == "confirmed"


def test_recovery_preserves_newer_catalogue_edits(setup_tags, tmp_path, monkeypatch):
    source, entry, preview = prepare_change(setup_tags, tmp_path)
    database, repository, catalog, codec, files = setup_tags
    confirm = catalog.confirm

    def concurrent(path, snapshot, observed, date_written):
        edit(database, entry.file_id, title="Newer catalogue title")
        return confirm(path, snapshot, observed, date_written)

    monkeypatch.setattr(catalog, "confirm", concurrent)
    report = WriteTagWrites(catalog, codec, files).execute(preview, (entry.file_id,))
    assert report.results[0].state == "catalog_pending"
    monkeypatch.setattr(catalog, "confirm", confirm)
    recovered = ReviewTagWrites(catalog, codec, files).execute(report.journal_path, reconcile=True)
    assert recovered.results[0].state == "conflict"
    assert repository.get(entry.file_id).metadata.title == "Newer catalogue title"
    assert read_metadata(source).title == "Corrected" and files.pending()


def test_version23_keeps_version_unicode_and_date_parts(setup_tags, tmp_path):
    from mutagen.id3 import TDAT, TIME, TYER

    database, repository, catalog, codec, files = setup_tags
    source = tmp_path / "legacy.mp3"
    source.write_bytes(REAL_MP3)
    tags = ID3()
    tags.add(TIT2(encoding=1, text=["Before"]))
    tags.add(TYER(encoding=1, text=["2020"]))
    tags.add(TDAT(encoding=1, text=["2902"]))
    tags.add(TIME(encoding=1, text=["1230"]))
    tags.save(source, v2_version=3)
    entry = repository.save(read_metadata(source), tmp_path, source.name)
    edit(database, entry.file_id, title="Canción Ω", album_year=2024)
    preview = PreviewTagWrites(catalog, codec, files).execute(
        TagWriteRequest(database, (entry.file_id,), ("title", "album_year"))
    )
    report = WriteTagWrites(catalog, codec, files).execute(preview, (entry.file_id,))
    assert report.results[0].state == "confirmed", report.results[0].message
    actual = ID3(source, translate=False)
    assert actual.version == (2, 3, 0)
    assert str(actual["TYER"]) == "2024" and str(actual["TDAT"]) == "2902"
    assert str(actual["TIME"]) == "1230" and str(actual["TIT2"]) == "Canción Ω"


def test_multiple_lyrics_require_selection_and_other_languages_survive(setup_tags, tmp_path):
    database, repository, catalog, codec, files = setup_tags
    source = make_source(tmp_path, "mp3")
    tags = ID3(source)
    tags.add(USLT(encoding=3, lang="spa", desc="Traducción", text="Texto anterior"))
    tags.save(source)
    entry = repository.save(read_metadata(source), source.parent, source.name)
    edit(database, entry.file_id, lyrics="Texto corregido")
    request = TagWriteRequest(database, (entry.file_id,), ("lyrics",))
    blocked = PreviewTagWrites(catalog, codec, files).execute(request)
    assert blocked.items[0].state == "blocked" and len(blocked.items[0].tags.lyrics_keys) == 2
    selected = "USLT:Traducción:spa"
    preview = PreviewTagWrites(catalog, codec, files).execute(
        replace(request, lyrics_keys=((entry.file_id, selected),))
    )
    report = WriteTagWrites(catalog, codec, files).execute(preview, (entry.file_id,))
    assert report.results[0].state == "confirmed", report.results[0].message
    actual = ID3(source)
    assert actual[selected].text == "Texto corregido"
    assert actual["USLT:Original:eng"].text == "Old lyrics"


@pytest.mark.parametrize("stage", ["temporary_verified", "written"])
def test_real_process_exit_recovers_durable_publication_state(setup_tags, tmp_path, stage):
    import subprocess
    import sys
    import textwrap

    source, entry, _ = prepare_change(setup_tags, tmp_path)
    database, _, catalog, codec, files = setup_tags
    program = textwrap.dedent("""
        import os, sys
        from pathlib import Path
        from trackfolio.application.write_tags import PreviewTagWrites, WriteTagWrites
        from trackfolio.domain.tag_write import TagWriteRequest
        from trackfolio.infrastructure.tag_write import MutagenTagCodec
        from trackfolio.infrastructure.tag_write_catalog import SqliteTagCatalog
        from trackfolio.infrastructure.tag_write_files import FileTagAccess, FileTagJournal
        database, file_id, root, stage = sys.argv[1:]
        catalog, codec, files = SqliteTagCatalog(), MutagenTagCodec(), FileTagAccess(Path(root))
        record = FileTagJournal.record
        def checkpoint(self, item, state, **details):
            if state == stage:
                os._exit(73)
            return record(self, item, state, **details)
        FileTagJournal.record = checkpoint
        preview = PreviewTagWrites(catalog, codec, files).execute(
            TagWriteRequest(Path(database), (int(file_id),), ("title",)))
        WriteTagWrites(catalog, codec, files).execute(preview, (int(file_id),))
    """)
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            program,
            str(database),
            str(entry.file_id),
            str(files.journal_root),
            stage,
        ],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 73, result.stdout + result.stderr
    operations = files.pending()
    assert len(operations) == 1
    report = ReviewTagWrites(catalog, codec, files).execute(
        operations[0].journal_path, reconcile=True
    )
    assert report.results[0].state == ("confirmed" if stage == "written" else "pending"), (
        report.results[0].message
    )
    assert read_metadata(source).title == ("Corrected" if stage == "written" else "Original")


def test_disk_full_stops_the_remaining_files(setup_tags, tmp_path, monkeypatch):
    import errno

    database, repository, catalog, codec, files = setup_tags
    sources = tuple(make_source(tmp_path, kind) for kind in ("flac", "mp3"))
    entries = tuple(
        repository.save(read_metadata(source), source.parent, source.name) for source in sources
    )
    for entry in entries:
        edit(database, entry.file_id, title="Corrected")
    before = tuple(source.read_bytes() for source in sources)
    preview = PreviewTagWrites(catalog, codec, files).execute(
        TagWriteRequest(database, tuple(entry.file_id for entry in entries), ("title",))
    )

    def full(*args):
        raise OSError(errno.ENOSPC, "No space")

    monkeypatch.setattr(files, "backup", full)
    report = WriteTagWrites(catalog, codec, files).execute(
        preview, tuple(entry.file_id for entry in entries)
    )
    assert [item.state for item in report.results] == ["failed", "pending"]
    assert report.fatal_error and tuple(source.read_bytes() for source in sources) == before


def test_unselected_album_sibling_keeps_its_original_date(setup_tags, tmp_path):
    database, repository, catalog, codec, files = setup_tags
    first = make_source(tmp_path, "flac")
    second = first.with_name("b.flac")
    second.write_bytes(first.read_bytes())
    first_entry = repository.save(read_metadata(first), first.parent, first.name)
    second_entry = repository.save(read_metadata(second), second.parent, second.name)
    edit(database, first_entry.file_id, album_year=2024)
    preview = PreviewTagWrites(catalog, codec, files).execute(
        TagWriteRequest(database, (first_entry.file_id,), ("album_year",))
    )
    report = WriteTagWrites(catalog, codec, files).execute(preview, (first_entry.file_id,))
    assert report.results[0].state == "confirmed", report.results[0].message
    assert repository.get(first_entry.file_id).metadata.album_date == "2024-02-29"
    assert repository.get(second_entry.file_id) == second_entry
    assert read_metadata(second).album_date == "2020-02-29"


@pytest.mark.parametrize("missing_at", [3, 4])
def test_missing_catalogue_stops_batch_before_or_after_publication(
    setup_tags, tmp_path, monkeypatch, missing_at
):
    database, repository, catalog, codec, files = setup_tags
    sources = tuple(make_source(tmp_path, kind) for kind in ("flac", "mp3"))
    entries = tuple(
        repository.save(read_metadata(source), source.parent, source.name) for source in sources
    )
    for entry in entries:
        edit(database, entry.file_id, title="Corrected")
    preview = PreviewTagWrites(catalog, codec, files).execute(
        TagWriteRequest(database, tuple(entry.file_id for entry in entries), ("title",))
    )
    identity = files.identity
    calls = 0

    def disappearing(path):
        nonlocal calls
        calls += 1
        if calls >= missing_at:
            raise FileNotFoundError("catalogue removed externally")
        return identity(path)

    monkeypatch.setattr(files, "identity", disappearing)
    report = WriteTagWrites(catalog, codec, files).execute(
        preview, tuple(entry.file_id for entry in entries)
    )
    assert report.fatal_error
    assert [item.state for item in report.results] == [
        "failed" if missing_at == 3 else "catalog_pending",
        "pending",
    ]
    assert read_metadata(sources[0]).title == ("Original" if missing_at == 3 else "Corrected")
    assert read_metadata(sources[1]).title == "Original"


@pytest.mark.parametrize("content", ["[]", '"text"', "null", "{", '{"schema": 1}'])
def test_corrupt_journals_do_not_hide_other_pending_operations(setup_tags, tmp_path, content):
    _, entry, preview = prepare_change(setup_tags, tmp_path)
    _, _, _, _, files = setup_tags
    valid = files.journal(preview)
    corrupt = files.journal_root / ("0" * 32) / "journal.json"
    corrupt.parent.mkdir()
    corrupt.write_text(content, encoding="utf-8")
    operations = files.pending()
    assert len(operations) == 2
    assert {item.journal_path for item in operations} == {corrupt, valid.path}
    assert next(item for item in operations if item.journal_path == corrupt).database_path is None


def test_replace_failure_keeps_original_and_verified_backup(setup_tags, tmp_path, monkeypatch):
    source, entry, preview = prepare_change(setup_tags, tmp_path)
    _, _, catalog, codec, files = setup_tags
    original = source.read_bytes()
    replace_file = os.replace

    def denied(incoming, destination):
        if destination == source:
            raise PermissionError("file is locked by another application")
        return replace_file(incoming, destination)

    monkeypatch.setattr(os, "replace", denied)
    report = WriteTagWrites(catalog, codec, files).execute(preview, (entry.file_id,))
    assert report.results[0].state == "failed"
    assert source.read_bytes() == original
    assert report.results[0].backup_path.read_bytes() == original
    assert not list(source.parent.glob(".trackfolio-*.tmp"))


@pytest.mark.skipif(os.name != "nt", reason="Windows sharing locks and NTFS streams")
def test_windows_delete_lock_and_named_stream_preservation(setup_tags, tmp_path):
    import ctypes
    from ctypes import wintypes

    source, entry, preview = prepare_change(setup_tags, tmp_path)
    _, _, catalog, codec, files = setup_tags
    original = source.read_bytes()
    stream = str(source) + ":trackfolio-test"
    with open(stream, "wb") as output:
        output.write(b"independent Windows stream")
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.CreateFileW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.c_void_p,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    # Allow reads/writes but withhold FILE_SHARE_DELETE, as native media players may do.
    handle = kernel.CreateFileW(str(source), 0x80000000, 3, None, 3, 0x80, None)
    assert handle != ctypes.c_void_p(-1).value
    try:
        report = WriteTagWrites(catalog, codec, files).execute(preview, (entry.file_id,))
        assert report.results[0].state == "failed", report
        assert source.read_bytes() == original
        assert report.results[0].backup_path.read_bytes() == original
    finally:
        kernel.CloseHandle(handle)
    updated = PreviewTagWrites(catalog, codec, files).execute(preview.request)
    report = WriteTagWrites(catalog, codec, files).execute(updated, (entry.file_id,))
    assert report.results[0].state == "confirmed", report
    with open(stream, "rb") as incoming:
        assert incoming.read() == b"independent Windows stream"


@pytest.mark.skipif(not hasattr(os, "setxattr"), reason="POSIX extended attributes")
def test_file_permissions_and_extended_attributes_survive(setup_tags, tmp_path):
    import errno

    source, entry, preview = prepare_change(setup_tags, tmp_path)
    _, _, catalog, codec, files = setup_tags
    source.chmod(0o640)
    key = "com.trackfolio.test" if os.uname().sysname == "Darwin" else "user.trackfolio-test"
    try:
        os.setxattr(source, key, b"unrelated attribute")
    except OSError as exc:
        if exc.errno in (errno.ENOTSUP, errno.EOPNOTSUPP):
            pytest.skip("Filesystem does not support extended attributes")
        raise
    report = WriteTagWrites(catalog, codec, files).execute(preview, (entry.file_id,))
    assert report.results[0].state == "confirmed", report
    assert source.stat().st_mode & 0o777 == 0o640
    assert os.getxattr(source, key) == b"unrelated attribute"
    assert os.getxattr(report.results[0].backup_path, key) == b"unrelated attribute"


def test_unknown_id3_frames_survive_without_reconstruction_from_catalogue(setup_tags, tmp_path):
    database, repository, catalog, codec, files = setup_tags
    source = make_source(tmp_path, "mp3")
    raw = source.read_bytes()
    payload = b"unknown binary payload\x00\xff"

    def synchsafe(size):
        return bytes((size >> shift) & 0x7F for shift in (21, 14, 7, 0))

    frame = b"XABC" + synchsafe(len(payload)) + b"\x00\x00" + payload
    size = sum(value << shift for value, shift in zip(raw[6:10], (21, 14, 7, 0), strict=True))
    source.write_bytes(raw[:6] + synchsafe(size + len(frame)) + frame + raw[10:])
    before = ID3(source, translate=False).unknown_frames
    assert before
    entry = repository.save(read_metadata(source), source.parent, source.name)
    edit(database, entry.file_id, title="Corrected")
    preview = PreviewTagWrites(catalog, codec, files).execute(
        TagWriteRequest(database, (entry.file_id,), ("title",))
    )
    report = WriteTagWrites(catalog, codec, files).execute(preview, (entry.file_id,))
    assert report.results[0].state == "confirmed", report.results[0].message
    assert ID3(source, translate=False).unknown_frames == before
