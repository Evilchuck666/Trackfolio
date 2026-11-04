"""Real FLAC/MP3 cover publication, source selection and catalogue observations."""

import json
from dataclasses import replace

import pytest
from mutagen.flac import FLAC
from mutagen.id3 import ID3
from test_catalog_edit import edit
from test_metadata import png
from test_tag_write import make_source
from test_tag_write import setup_tags as setup_tags

from trackfolio.application.cover_writes import CoverSelectionRequired
from trackfolio.application.write_tags import TagWriteConflict, TagWriteService
from trackfolio.domain.tag_write import CoverChoice
from trackfolio.infrastructure.album_nfo import XmlAlbumNfoCodec
from trackfolio.infrastructure.cover_files import MAX_COVER_BYTES, FileCoverAccess
from trackfolio.infrastructure.metadata import read_metadata


def service_for(setup_tags):
    _, _, catalog, codec, files = setup_tags
    return TagWriteService(
        catalog, codec, files, nfo_codec=XmlAlbumNfoCodec(), cover_sources=FileCoverAccess()
    )


def pictures(source):
    if source.suffix == ".flac":
        return [(p.type, p.mime, p.data, p.desc) for p in FLAC(source).pictures]
    return [(p.type, p.mime, p.data, p.desc) for p in ID3(source).getall("APIC")]


def front(source):
    return [(mime, data) for kind, mime, data, _ in pictures(source) if kind == 3]


@pytest.mark.parametrize("kind", ["flac", "mp3"])
def test_one_png_replaces_front_only_and_updates_sqlite_without_text_changes(
    setup_tags, tmp_path, kind
):
    database, repository, _, _, _ = setup_tags
    source = make_source(tmp_path, kind)
    entry = repository.save(read_metadata(source), source.parent, source.name)
    other_pictures = [p for p in pictures(source) if p[0] != 3]
    image = source.parent / "folder.PNG"
    data = png(3, 2, (0, 255, 0))
    image.write_bytes(data)
    report = service_for(setup_tags).execute(database, (entry.file_id,))
    assert report.results[0].state == "confirmed", report
    assert report.results[0].cover_action == ("replaced" if kind == "flac" else "embedded")
    assert front(source) == [("image/png", data)]
    assert [p for p in pictures(source) if p[0] != 3] == other_pictures
    actual = repository.get(entry.file_id).metadata
    assert actual.artwork.data == data and actual.artwork.source == "embedded"
    assert actual.artwork.source_path is None
    assert image.read_bytes() == data
    original, info = source.read_bytes(), source.stat()
    again = service_for(setup_tags).execute(database, (entry.file_id,))
    assert again.results[0].state == "unchanged", again
    assert again.results[0].cover_action == "unchanged"
    assert source.read_bytes() == original and source.stat().st_ino == info.st_ino
    assert source.stat().st_mtime_ns == info.st_mtime_ns
    assert not (source.parent / ".trackfolio-backups").exists()
    journal = json.loads(report.journal_path.read_text(encoding="utf-8"))
    assert journal["schema"] == 3
    assert "data" not in journal["preview"]["items"][0]["tags"]["cover"]


@pytest.mark.parametrize("kind", ["flac", "mp3"])
def test_no_images_preserves_existing_cover_and_allows_text_write(setup_tags, tmp_path, kind):
    database, repository, _, _, _ = setup_tags
    source = make_source(tmp_path, kind)
    before = pictures(source)
    entry = repository.save(read_metadata(source), source.parent, source.name)
    nfo = source.parent / "album.nfo"
    nfo.write_text("<album><thumb>old.jpg</thumb></album>", encoding="utf-8")
    edit(database, entry.file_id, title="Text only")
    report = service_for(setup_tags).execute(database, (entry.file_id,))
    assert report.results[0].state == "confirmed", report
    assert pictures(source) == before
    assert report.results[0].cover_action == "preserved"
    assert "<thumb>old.jpg</thumb>" in nfo.read_text(encoding="utf-8")


def test_multiple_images_require_explicit_choice_before_any_write(setup_tags, tmp_path):
    database, repository, _, _, files = setup_tags
    source = make_source(tmp_path, "flac")
    entry = repository.save(read_metadata(source), source.parent, source.name)
    first, second = source.parent / "album.jpg", source.parent / "other.png"
    first.write_bytes(png(2, 2))
    second.write_bytes(png(3, 3))
    nfo = source.parent / "album.nfo"
    nfo.write_text("<album/>", encoding="utf-8")
    original, nfo_original = source.read_bytes(), nfo.read_bytes()
    service = service_for(setup_tags)
    with pytest.raises(CoverSelectionRequired) as required:
        service.execute(database, (entry.file_id,))
    assert source.read_bytes() == original and nfo.read_bytes() == nfo_original
    assert not files.journal_root.exists()
    report = service.execute(
        database,
        (entry.file_id,),
        cover_discovery=required.value.discovery,
        cover_choices=(CoverChoice(source.parent, second),),
    )
    assert report.results[0].state == "confirmed", report
    assert front(source) == [("image/png", second.read_bytes())]
    assert "<thumb>other.png</thumb>" in nfo.read_text(encoding="utf-8")


@pytest.mark.parametrize("existing", ["", "    <thumb>old.jpg</thumb>\n"])
@pytest.mark.parametrize("already_embedded", [False, True])
def test_selected_cover_updates_nfo_even_when_audio_matches(
    setup_tags, tmp_path, existing, already_embedded
):
    database, repository, _, _, files = setup_tags
    source = make_source(tmp_path, "flac")
    entry = repository.save(read_metadata(source), source.parent, source.name)
    data = front(source)[0][1] if already_embedded else png(3, 2, (0, 255, 0))
    (source.parent / "new & cover.png").write_bytes(data)
    nfo = source.parent / "album.nfo"
    nfo.write_text(
        '<?xml version="1.0"?>\n<album>\n    <title>Old album</title>\n' + existing + "</album>\n",
        encoding="utf-8",
    )
    service = service_for(setup_tags)
    report = service.execute(database, (entry.file_id,))
    assert report.nfo_results[0].state == "updated", report
    assert "    <thumb>new &amp; cover.png</thumb>\n" in nfo.read_text(encoding="utf-8")
    assert front(source) == [("image/png", data)]
    recovered = files.load_journal(report.journal_path)
    assert recovered.preview.nfo_items[0].values.thumb == "new & cover.png"
    before = nfo.read_bytes()
    again = service.execute(database, (entry.file_id,))
    assert again.nfo_results[0].state == "unchanged", again
    assert nfo.read_bytes() == before


def test_skip_preserves_cover_and_allows_other_tags(setup_tags, tmp_path):
    database, repository, _, _, _ = setup_tags
    source = make_source(tmp_path, "flac")
    entry = repository.save(read_metadata(source), source.parent, source.name)
    for name in ("a.jpg", "b.png"):
        (source.parent / name).write_bytes(png(3, 2))
    old = pictures(source)
    nfo = source.parent / "album.nfo"
    nfo.write_text("<album><thumb>old.jpg</thumb></album>", encoding="utf-8")
    edit(database, entry.file_id, title="Text only")
    service = service_for(setup_tags)
    discovery = service.discover_covers(database, (entry.file_id,))
    report = service.execute(
        database,
        (entry.file_id,),
        cover_discovery=discovery,
        cover_choices=(CoverChoice(source.parent, None),),
    )
    assert report.results[0].state == "confirmed", report
    assert report.results[0].cover_action == "skipped" and pictures(source) == old
    assert "<thumb>old.jpg</thumb>" in nfo.read_text(encoding="utf-8")


def test_catalogue_only_refresh_does_not_replace_audio(setup_tags, tmp_path):
    database, repository, _, _, _ = setup_tags
    source = make_source(tmp_path, "flac")
    entry = repository.save(
        replace(read_metadata(source), artwork=None), source.parent, source.name
    )
    (source.parent / "front.png").write_bytes(front(source)[0][1])
    before, info = source.read_bytes(), source.stat()
    report = service_for(setup_tags).execute(database, (entry.file_id,))
    assert report.results[0].state == "unchanged", report
    assert report.results[0].catalog_updated
    assert source.read_bytes() == before and source.stat().st_ino == info.st_ino
    assert repository.get(entry.file_id).metadata.artwork.data == front(source)[0][1]
    assert not (source.parent / ".trackfolio-backups").exists()


@pytest.mark.parametrize("mutation", ["source", "inventory", "catalog"])
def test_changes_after_discovery_do_not_publish(setup_tags, tmp_path, mutation):
    database, repository, _, _, _ = setup_tags
    source = make_source(tmp_path, "flac")
    entry = repository.save(read_metadata(source), source.parent, source.name)
    image = source.parent / "front.png"
    image.write_bytes(png(3, 2))
    service = service_for(setup_tags)
    discovery = service.discover_covers(database, (entry.file_id,))
    original = source.read_bytes()
    if mutation == "catalog":
        edit(database, entry.file_id, title="Concurrent")
        with pytest.raises(TagWriteConflict):
            service.execute(database, (entry.file_id,), cover_discovery=discovery)
    else:
        if mutation == "source":
            image.write_bytes(png(4, 4))
        else:
            (source.parent / "new.png").write_bytes(png())
        report = service.execute(database, (entry.file_id,), cover_discovery=discovery)
        assert report.results[0].state in ("failed", "excluded", "conflict"), report
    assert source.read_bytes() == original


@pytest.mark.parametrize(
    "bad", [b"", b"broken", b"x" * (MAX_COVER_BYTES + 1)], ids=["empty", "broken", "oversized"]
)
def test_bad_single_image_blocks_music_and_preserves_cover(setup_tags, tmp_path, bad):
    database, repository, _, _, _ = setup_tags
    source = make_source(tmp_path, "flac")
    entry = repository.save(read_metadata(source), source.parent, source.name)
    (source.parent / "front.jpg").write_bytes(bad)
    original = source.read_bytes()
    report = service_for(setup_tags).execute(database, (entry.file_id,))
    assert report.results[0].state == "failed", report
    assert source.read_bytes() == original


def test_source_changes_before_publish_preserve_backup_and_original(
    setup_tags, tmp_path, monkeypatch
):
    database, repository, _, codec, _ = setup_tags
    source = make_source(tmp_path, "flac")
    entry = repository.save(read_metadata(source), source.parent, source.name)
    image = source.parent / "front.png"
    image.write_bytes(png(3, 2))
    write = codec.write_verified

    def changed(*args):
        observed = write(*args)
        image.write_bytes(png(4, 4))
        return observed

    monkeypatch.setattr(codec, "write_verified", changed)
    original = source.read_bytes()
    report = service_for(setup_tags).execute(database, (entry.file_id,))
    assert report.results[0].state == "conflict", report
    assert report.results[0].backup_path.is_file() and source.read_bytes() == original


@pytest.mark.parametrize("version", [3, 4])
def test_mp3_duplicate_fronts_preserve_other_images_and_id3_version(setup_tags, tmp_path, version):
    from mutagen.id3 import APIC

    database, repository, _, _, _ = setup_tags
    source = make_source(tmp_path, "mp3")
    tags = ID3(source)
    for kind, desc in ((3, "one"), (3, "two"), (4, "Cover (front)"), (0, "Unknown")):
        tags.add(APIC(encoding=1, type=kind, mime="image/png", desc=desc, data=png(kind + 1, 2)))
    tags.save(source, v2_version=version)
    before = [p for p in pictures(source) if p[0] != 3]
    entry = repository.save(read_metadata(source), source.parent, source.name)
    image = png(5, 5)
    (source.parent / "cover.png").write_bytes(image)
    report = service_for(setup_tags).execute(database, (entry.file_id,))
    assert report.results[0].state == "confirmed", report
    assert ID3(source, translate=False).version[:2] == (2, version)
    assert front(source) == [("image/png", image)]
    assert [p for p in pictures(source) if p[0] != 3] == before


def test_flac_duplicate_fronts_and_non_front_attributes_are_preserved(setup_tags, tmp_path):
    from mutagen.flac import Picture

    database, repository, _, _, _ = setup_tags
    source = make_source(tmp_path, "flac")
    audio = FLAC(source)
    picture = Picture()
    picture.type, picture.desc, picture.mime = 3, "Duplicate", "image/png"
    picture.width, picture.height, picture.depth = 2, 2, 24
    picture.data = png(2, 2)
    audio.add_picture(picture)
    audio.save()
    before = [p.write() for p in FLAC(source).pictures if p.type != 3]
    entry = repository.save(read_metadata(source), source.parent, source.name)
    (source.parent / "front.png").write_bytes(png(7, 3))
    report = service_for(setup_tags).execute(database, (entry.file_id,))
    assert report.results[0].state == "confirmed", report
    assert len(front(source)) == 1
    assert [p.write() for p in FLAC(source).pictures if p.type != 3] == before


@pytest.mark.parametrize("suffix", [".jpg", ".JPEG", ".PNG"])
def test_source_extensions_and_root_alias(setup_tags, tmp_path, suffix):
    import os

    database, repository, _, _, _ = setup_tags
    source = make_source(tmp_path, "mp3")
    alias = tmp_path / "alias"
    try:
        alias.symlink_to(source.parent, target_is_directory=True)
    except OSError:
        if os.name == "nt":
            pytest.skip("Directory symlink privilege unavailable")
        raise
    entry = repository.save(read_metadata(source), alias, source.name)
    # Recognition follows contents, independently of the extension.
    image = png(6, 2)
    (source.parent / ("cover" + suffix)).write_bytes(image)
    report = service_for(setup_tags).execute(database, (entry.file_id,))
    assert report.results[0].state == "confirmed", report
    assert front(source) == [("image/png", image)]
    loaded = setup_tags[4].load_journal(report.journal_path)
    assert loaded.preview.items[0].tags.cover.path.parent == source.parent


def test_partial_selection_keeps_unselected_audio_untouched(setup_tags, tmp_path):
    database, repository, _, _, _ = setup_tags
    source = make_source(tmp_path, "flac")
    other = source.with_name("unselected.flac")
    other.write_bytes(source.read_bytes())
    first = repository.save(read_metadata(source), source.parent, source.name)
    repository.save(read_metadata(other), other.parent, other.name)
    before = other.read_bytes()
    (source.parent / "front.png").write_bytes(png(8, 2))
    report = service_for(setup_tags).execute(database, (first.file_id,))
    assert report.results[0].state == "confirmed", report
    assert other.read_bytes() == before


def test_two_folders_share_one_explicit_choice_each(setup_tags, tmp_path):
    database, repository, _, _, _ = setup_tags
    sources, entries, choices = [], [], []
    for name in ("first", "second"):
        directory = tmp_path / name
        directory.mkdir()
        source = make_source(directory, "flac")
        sources.append(source)
        entries.append(repository.save(read_metadata(source), source.parent, source.name))
        for size, filename in ((2, "one.png"), (3, "two.png")):
            (source.parent / filename).write_bytes(png(size, 2))
        choices.append(CoverChoice(source.parent, source.parent / "two.png"))
    service = service_for(setup_tags)
    ids = tuple(entry.file_id for entry in entries)
    discovery = service.discover_covers(database, ids)
    with pytest.raises(CoverSelectionRequired):
        service.execute(database, ids, cover_discovery=discovery, cover_choices=tuple(choices[:1]))
    report = service.execute(database, ids, cover_discovery=discovery, cover_choices=tuple(choices))
    assert all(result.state == "confirmed" for result in report.results), report
    assert all(front(source) == [("image/png", png(3, 2))] for source in sources)


def test_album_jpg_fallback_cannot_mask_a_failed_embedding(setup_tags, tmp_path, monkeypatch):
    database, repository, _, codec, _ = setup_tags
    source = make_source(tmp_path, "mp3")
    image = png(9, 3)
    (source.parent / "album.jpg").write_bytes(image)
    entry = repository.save(read_metadata(source), source.parent, source.name)
    assert not front(source) and read_metadata(source).artwork.data == image
    monkeypatch.setattr(codec, "_write_mp3", lambda *_: None)
    original = source.read_bytes()
    report = service_for(setup_tags).execute(database, (entry.file_id,))
    assert report.results[0].state == "failed", report
    assert source.read_bytes() == original and not front(source)
    assert report.results[0].backup_path.is_file()


def test_catalogue_pending_cover_is_reconciled_from_journal_without_source(
    setup_tags, tmp_path, monkeypatch
):
    database, repository, catalog, _, files = setup_tags
    source = make_source(tmp_path, "flac")
    entry = repository.save(read_metadata(source), source.parent, source.name)
    image = source.parent / "front.png"
    data = png(8, 3)
    image.write_bytes(data)
    confirm = catalog.confirm

    def unavailable(*args, **kwargs):
        raise OSError("SQLite temporarily unavailable")

    monkeypatch.setattr(catalog, "confirm", unavailable)
    service = service_for(setup_tags)
    report = service.execute(database, (entry.file_id,))
    assert report.results[0].state == "catalog_pending", report
    assert front(source) == [("image/png", data)]
    assert report.results[0].backup_path.is_file()
    image.unlink()
    monkeypatch.setattr(catalog, "confirm", confirm)
    review = service.reviewer.execute(report.journal_path, reconcile=True)
    assert review.results[0].state == "confirmed", review
    assert review.results[0].cover_action == "replaced"
    assert repository.get(entry.file_id).metadata.artwork.data == data
    assert files.load_journal(report.journal_path).preview.items[0].tags.cover.data is None


def test_cancel_before_discovery_writes_nothing(setup_tags, tmp_path):
    database, repository, _, _, files = setup_tags
    source = make_source(tmp_path, "flac")
    entry = repository.save(read_metadata(source), source.parent, source.name)
    (source.parent / "front.png").write_bytes(png(4, 3))
    before = source.read_bytes()
    report = service_for(setup_tags).execute(database, (entry.file_id,), is_cancelled=lambda: True)
    assert report.cancelled and source.read_bytes() == before
    assert not files.journal_root.exists()


@pytest.mark.parametrize("kind", ["flac", "mp3"])
def test_real_jpeg_bytes_are_embedded_without_conversion(setup_tags, tmp_path, kind):
    import base64

    database, repository, _, _, _ = setup_tags
    source = make_source(tmp_path, kind)
    entry = repository.save(read_metadata(source), source.parent, source.name)
    data = base64.b64decode(
        "/9j/4AAQSkZJRgABAQEAZABkAAD/2wBDAAgGBgcGBQgHBwcJCQgKDBQNDAsLDBkSEw8UHRofHh0aHBwgJC4nICIs"
        "IxwcKDcpLDAxNDQ0Hyc5PTgyPC4zNDL/2wBDAQkJCQwLDBgNDRgyIRwhMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIy"
        "MjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjL/wAARCAADAAIDASIAAhEBAxEB/8QAHwAAAQUBAQEBAQEAAAAAAAAA"
        "AAECAwQFBgcICQoL/8QAtRAAAgEDAwIEAwUFBAQAAAF9AQIDAAQRBRIhMUEGE1FhByJxFDKBkaEII0KxwRVS0fAk"
        "M2JyggkKFhcYGRolJicoKSo0NTY3ODk6Q0RFRkdISUpTVFVWV1hZWmNkZWZnaGlqc3R1dnd4eXqDhIWGh4iJipKT"
        "lJWWl5iZmqKjpKWmp6ipqrKztLW2t7i5usLDxMXGx8jJytLT1NXW19jZ2uHi4+Tl5ufo6erx8vP09fb3+Pn6/8QA"
        "HwEAAwEBAQEBAQEBAQAAAAAAAAECAwQFBgcICQoL/8QAtREAAgECBAQDBAcFBAQAAQJ3AAECAxEEBSExBhJBUQdh"
        "cRMiMoEIFEKRobHBCSMzUvAVYnLRChYkNOEl8RcYGRomJygpKjU2Nzg5OkNERUZHSElKU1RVVldYWVpjZGVmZ2hp"
        "anN0dXZ3eHl6goOEhYaHiImKkpOUlZaXmJmaoqOkpaanqKmqsrO0tba3uLm6wsPExcbHyMnK0tPU1dbX2Nna4uPk"
        "5ebn6Onq8vP09fb3+Pn6/9oADAMBAAIRAxEAPwDLooor5k+EP//Z"
    )
    (source.parent / "Cover.JPEG").write_bytes(data)
    report = service_for(setup_tags).execute(database, (entry.file_id,))
    assert report.results[0].state == "confirmed", report
    assert front(source) == [("image/jpeg", data)]
    artwork = repository.get(entry.file_id).metadata.artwork
    assert (artwork.width, artwork.height, artwork.mime_type) == (2, 3, "image/jpeg")


@pytest.mark.parametrize("kind", ["flac", "mp3"])
def test_cover_replacement_preserves_encoded_audio_payload(setup_tags, tmp_path, kind):
    from audio_samples import FLAC as REAL_FLAC
    from audio_samples import MP3 as REAL_MP3

    from trackfolio.infrastructure.tag_write import _flac_layout, _mp3_payload

    database, repository, _, _, _ = setup_tags
    source = tmp_path / ("real." + kind)
    source.write_bytes(REAL_FLAC if kind == "flac" else REAL_MP3)
    payload = _flac_layout(source)[0] if kind == "flac" else _mp3_payload(source)
    entry = repository.save(read_metadata(source), source.parent, source.name)
    data = png(10, 3)
    (tmp_path / "front.png").write_bytes(data)
    report = service_for(setup_tags).execute(database, (entry.file_id,))
    assert report.results[0].state == "confirmed", report
    actual = _flac_layout(source)[0] if kind == "flac" else _mp3_payload(source)
    assert actual == payload and front(source) == [("image/png", data)]


def test_linked_image_is_not_followed(setup_tags, tmp_path):
    import os

    database, repository, _, _, _ = setup_tags
    source = make_source(tmp_path, "flac")
    entry = repository.save(read_metadata(source), source.parent, source.name)
    external = tmp_path / "outside.png"
    external.write_bytes(png())
    try:
        (source.parent / "cover.png").symlink_to(external)
    except OSError:
        if os.name == "nt":
            pytest.skip("Symlink privilege unavailable")
        raise
    before = source.read_bytes()
    report = service_for(setup_tags).execute(database, (entry.file_id,))
    assert report.results[0].state == "failed", report
    assert source.read_bytes() == before


def test_readonly_image_is_a_valid_source_and_jpg_directories_are_ignored(setup_tags, tmp_path):
    database, repository, _, _, _ = setup_tags
    source = make_source(tmp_path, "mp3")
    entry = repository.save(read_metadata(source), source.parent, source.name)
    image = source.parent / "front.png"
    image.write_bytes(png(11, 3))
    image.chmod(0o444)
    (source.parent / "directory.jpg").mkdir()
    try:
        report = service_for(setup_tags).execute(database, (entry.file_id,))
        assert report.results[0].state == "confirmed", report
        assert front(source) == [("image/png", image.read_bytes())]
    finally:
        image.chmod(0o644)


def test_cover_growth_is_included_in_space_reservation(setup_tags, tmp_path, monkeypatch):
    from collections import namedtuple

    import trackfolio.infrastructure.tag_write_files as module

    database, repository, _, _, _ = setup_tags
    source = make_source(tmp_path, "mp3")
    entry = repository.save(read_metadata(source), source.parent, source.name)
    (source.parent / "front.png").write_bytes(png(12, 3))
    # Just enough for the former text-only estimate, insufficient for the image.
    free = 2 * source.stat().st_size + 1024 * 1024
    usage = namedtuple("usage", "total used free")
    monkeypatch.setattr(module.shutil, "disk_usage", lambda _: usage(free, 0, free))
    original = source.read_bytes()
    report = service_for(setup_tags).execute(database, (entry.file_id,))
    assert report.fatal_error and report.results[0].state == "pending", report
    assert source.read_bytes() == original


def test_concurrent_sqlite_artwork_change_is_a_conflict(setup_tags, tmp_path):
    from sqlalchemy import update

    from trackfolio.infrastructure.database import artworks, create_engine

    database, repository, _, _, _ = setup_tags
    source = make_source(tmp_path, "flac")
    entry = repository.save(read_metadata(source), source.parent, source.name)
    (source.parent / "front.png").write_bytes(png(13, 3))
    service = service_for(setup_tags)
    discovery = service.discover_covers(database, (entry.file_id,))
    engine = create_engine(database)
    try:
        with engine.begin() as connection:
            connection.execute(update(artworks).values(data=png(14, 3)))
    finally:
        engine.dispose()
    original = source.read_bytes()
    with pytest.raises(TagWriteConflict):
        service.execute(database, (entry.file_id,), cover_discovery=discovery)
    assert source.read_bytes() == original


def test_root_alias_target_change_during_selection_does_not_write_either_album(
    setup_tags, tmp_path
):
    import os

    database, repository, _, _, files = setup_tags
    original_root = tmp_path / "original"
    replacement_root = tmp_path / "replacement"
    original_root.mkdir()
    replacement_root.mkdir()
    source = make_source(original_root, "flac")
    other = make_source(replacement_root, "flac")
    alias = tmp_path / "library"
    try:
        alias.symlink_to(source.parent, target_is_directory=True)
    except OSError:
        if os.name == "nt":
            pytest.skip("Directory symlink privilege unavailable")
        raise
    entry = repository.save(read_metadata(source), alias, source.name)
    (source.parent / "cover.png").write_bytes(png(15, 3))
    service = service_for(setup_tags)
    discovery = service.discover_covers(database, (entry.file_id,))
    before, other_before = source.read_bytes(), other.read_bytes()
    alias.unlink()
    alias.symlink_to(other.parent, target_is_directory=True)
    with pytest.raises(TagWriteConflict):
        service.execute(database, (entry.file_id,), cover_discovery=discovery)
    assert source.read_bytes() == before and other.read_bytes() == other_before
    assert not files.journal_root.exists()


def test_no_sidecar_does_not_embed_catalogue_or_nfo_artwork(setup_tags, tmp_path):
    from trackfolio.domain.metadata import Artwork

    database, repository, _, _, _ = setup_tags
    source = make_source(tmp_path, "mp3")
    outside = tmp_path / "album.jpg"
    outside.write_bytes(png(16, 3))
    entry = repository.save(
        replace(read_metadata(source), artwork=Artwork(png(17, 3), "image/png", 17, 3)),
        source.parent,
        source.name,
    )
    (source.parent / "album.nfo").write_text(
        f"<album><thumb>{outside.as_posix()}</thumb></album>", encoding="utf-8"
    )
    before = source.read_bytes()
    report = service_for(setup_tags).execute(database, (entry.file_id,))
    assert report.results[0].state == "unchanged", report
    assert source.read_bytes() == before and not front(source)
    assert repository.get(entry.file_id).metadata.artwork.data == png(17, 3)
