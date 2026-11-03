"""Real XML sidecars participate in the same recoverable operation as audio."""

import codecs
import json
import os
import shutil
from dataclasses import replace
from pathlib import PureWindowsPath
from xml.dom import minidom

import pytest
from test_catalog_edit import edit
from test_tag_write import make_source
from test_tag_write import setup_tags as setup_tags

from trackfolio.application.write_tags import (
    TagPublishedError,
    TagWriteConflict,
    TagWriteError,
    TagWriteService,
)
from trackfolio.domain.catalog_edit import EDIT_FIELDS
from trackfolio.domain.tag_write import AlbumNfoSong, AlbumNfoValues, TagWriteRequest
from trackfolio.infrastructure.album_nfo import MAX_NFO_BYTES, XmlAlbumNfoCodec
from trackfolio.infrastructure.metadata import read_metadata

VALUES = AlbumNfoValues("New & Ω", 2021, ("Metal", "Rock; /"), ("Artist & Ω",))


def xml_values(path, name):
    document = minidom.parse(str(path))
    return [
        "".join(child.data for child in element.childNodes if child.nodeType in (3, 4))
        for element in document.documentElement.childNodes
        if element.nodeType == 1 and element.tagName == name
    ]


def change_xml(tmp_path, content, values=VALUES):
    source = tmp_path / "album.nfo"
    source.write_bytes(content if isinstance(content, bytes) else content.encode())
    target = tmp_path / "copy.tmp"
    codec = XmlAlbumNfoCodec()
    assert codec.plan(source, values)
    codec.write_verified(source, target, values)
    assert not codec.plan(target, values)
    return target


def test_codec_changes_managed_fields_and_preserves_document(tmp_path):
    target = change_xml(
        tmp_path,
        """<?xml version="1.0" encoding="UTF-8"?>
<?before keep?>
<!--before--><album custom="yes">
 <title sort="keep">Old<!--inside--></title><year>2020</year><year>1999</year>
 <releasedate>2020-02-29</releasedate><originalreleasedate>1980-01-02</originalreleasedate>
 <review><![CDATA[Review <text> & music]]></review><genre>Old</genre>
 <label id="42">Label</label><thumb preview="url">image</thumb><rating max="10">9</rating>
 <unknown><title>Nested</title></unknown><track><title>Track</title><position>2</position></track>
 <albumArtistCredits><artist>Old</artist></albumArtistCredits><artistdesc>Old</artistdesc>
</album><!--after--><?after keep?>""",
    )
    text = target.read_text(encoding="utf-8")
    assert xml_values(target, "title") == ["New & Ω"]
    assert xml_values(target, "year") == ["2021"]
    assert xml_values(target, "releasedate") == ["2021"]  # Invalid leap day is reduced.
    assert xml_values(target, "genre") == ["Metal", "Rock; /"]
    assert xml_values(target, "artistdesc") == ["Artist & Ω"]
    for kept in (
        "<!--inside-->",
        "<!--before-->",
        "<!--after-->",
        "<?before keep?>",
        "<?after keep?>",
        "<![CDATA[Review <text> & music]]>",
        "<title>Nested</title>",
        "<title>Track</title>",
        "<originalreleasedate>1980-01-02</originalreleasedate>",
        'sort="keep"',
        'custom="yes"',
        '<label id="42">Label</label>',
        '<thumb preview="url">image</thumb>',
        '<rating max="10">9</rating>',
    ):
        assert kept in text


@pytest.mark.parametrize("indent", ["    ", "\t"])
@pytest.mark.parametrize("newline", ["\n", "\r\n"])
def test_added_genres_stay_together_and_preserve_indentation(tmp_path, indent, newline):
    original = newline.join(
        [
            '<?xml version="1.0" encoding="utf-8"?>',
            "<album>",
            f"{indent}<title>Abbath</title>",
            f"{indent}<genre>Thrash Metal</genre>",
            f"{indent}<track><position>1</position><title>Keep</title></track>",
            "</album>",
            "",
        ]
    )
    values = AlbumNfoValues("Abbath", None, ("Thrash Metal", "Black Metal", "Metal"), None)
    target = change_xml(tmp_path, original, values)
    expected = original.replace(
        "<genre>Thrash Metal</genre>",
        f"<genre>Thrash Metal</genre>{newline}{indent}<genre>Black Metal</genre>"
        f"{newline}{indent}<genre>Metal</genre>",
    )
    assert target.read_bytes() == expected.encode()


def test_missing_field_is_inserted_before_closing_indentation(tmp_path):
    original = '<?xml version="1.0"?>\n<album>\n  <title>Abbath</title>\n</album>\n'
    target = change_xml(tmp_path, original, AlbumNfoValues("Abbath", None, ("Metal",), None))
    assert (
        target.read_bytes()
        == original.replace("\n</album>", "\n  <genre>Metal</genre>\n</album>").encode()
    )


def test_namespaced_extension_fields_are_preserved(tmp_path):
    target = change_xml(tmp_path, '<album><title xmlns="urn:extension">Keep</title></album>')
    doc = minidom.parse(str(target))
    assert doc.getElementsByTagNameNS("urn:extension", "title")[0].firstChild.data == "Keep"
    assert not XmlAlbumNfoCodec().plan(target, VALUES)


@pytest.mark.parametrize(
    "previous,expected",
    [
        ("2020-03-12", "2021-03-12"),
        ("2020-03", "2021-03"),
        ("2020", "2021"),
        ("garbage", "2021"),
        ("2020-13-01", "2021"),
    ],
)
def test_release_date_precision(tmp_path, previous, expected):
    target = change_xml(tmp_path, f"<album><releasedate>{previous}</releasedate></album>")
    assert xml_values(target, "releasedate") == [expected]


def test_clearing_removes_managed_values_only(tmp_path):
    target = change_xml(
        tmp_path,
        """<album><title>Old</title><year>2020</year><genre>Metal</genre>
<releasedate>2020</releasedate><originalreleasedate>1980</originalreleasedate>
<artistdesc>A</artistdesc><albumArtistCredits><artist>A</artist></albumArtistCredits></album>""",
        AlbumNfoValues(None, None, (), ()),
    )
    for name in ("title", "year", "genre", "releasedate", "albumArtistCredits", "artistdesc"):
        assert xml_values(target, name) == []
    assert xml_values(target, "originalreleasedate") == ["1980"]


@pytest.mark.parametrize(
    "encoding,bom", [("utf-8", True), ("utf-16", False), ("iso-8859-1", False)]
)
def test_encoding_bom_and_crlf(tmp_path, encoding, bom):
    content = (
        f'<?xml version="1.0" encoding="{encoding}"?>\r\n<album>\r\n<title>Old</title>\r\n</album>'
    )
    data = content.encode(encoding)
    if bom:
        data = codecs.BOM_UTF8 + data
    target = change_xml(tmp_path, data)
    result = target.read_bytes()
    assert "\r\n" in result.decode(encoding)
    if bom:
        assert result.startswith(codecs.BOM_UTF8)


@pytest.mark.parametrize("encoding", ["utf-8", "utf-16", "iso-8859-1"])
@pytest.mark.parametrize("gap", ["\n", "\r\n", "\n\n  "])
def test_xml_declaration_gap_and_final_newline_are_preserved(tmp_path, encoding, gap):
    header = f'<?xml version="1.0" encoding="{encoding}"?>'
    newline = "\r\n" if "\r\n" in gap else "\n"
    original = f"{header}{gap}<album><title>Old</title><artist>Abbath</artist></album>{newline}"
    target = change_xml(tmp_path, original.encode(encoding), replace(VALUES, artists=("Abbath",)))
    written = target.read_bytes().decode(encoding)
    assert written.startswith(header + gap + "<album>")
    assert written.endswith("</album>" + newline)
    assert "albumArtistCredits" not in written


def test_joined_header_can_be_repaired_without_metadata_differences(tmp_path):
    values = AlbumNfoValues("Abbath", None, (), ("Abbath",))
    target = change_xml(
        tmp_path,
        '<?xml version="1.0" encoding="utf-8"?><album><title>Abbath</title>'
        "<artist>Abbath</artist></album>",
        values,
    )
    assert target.read_text(encoding="utf-8").startswith(
        '<?xml version="1.0" encoding="utf-8"?>\n<album>'
    )
    assert "albumArtistCredits" not in target.read_text(encoding="utf-8")


@pytest.mark.parametrize("credit_name", ["Abbath", "Stale credits"])
def test_plain_duplicate_artist_credits_are_removed_without_other_changes(tmp_path, credit_name):
    values = AlbumNfoValues("Abbath", None, (), ("Abbath",))
    target = change_xml(
        tmp_path,
        '<?xml version="1.0" encoding="utf-8"?>\n<album><title>Abbath</title>'
        "<artist>Abbath</artist>\n"
        f"<albumArtistCredits><artist>{credit_name}</artist></albumArtistCredits></album>\n",
        values,
    )
    assert xml_values(target, "artist") == ["Abbath"]
    assert "albumArtistCredits" not in target.read_text(encoding="utf-8")
    assert target.read_text(encoding="utf-8").endswith("</album>\n")


def test_rich_artist_credits_are_preserved_when_direct_artist_also_exists(tmp_path):
    target = change_xml(
        tmp_path,
        "<album><title>Old</title><artist>Abbath</artist>"
        "<albumArtistCredits><artist>Abbath</artist>"
        "<musicBrainzArtistID>keep-id</musicBrainzArtistID></albumArtistCredits></album>",
        replace(VALUES, artists=("Abbath",)),
    )
    assert "<musicBrainzArtistID>keep-id</musicBrainzArtistID>" in target.read_text(
        encoding="utf-8"
    )


def test_artist_updates_use_existing_representation_without_new_credits(tmp_path):
    target = change_xml(tmp_path, "<album><artist>Old</artist></album>")
    assert xml_values(target, "artist") == ["Artist & Ω"]
    assert "albumArtistCredits" not in target.read_text(encoding="utf-8")


def test_missing_artist_representation_does_not_create_credit_elements(tmp_path):
    target = change_xml(tmp_path, "<album><title>Old</title></album>")
    assert not xml_values(target, "artist")
    assert "albumArtistCredits" not in target.read_text(encoding="utf-8")


@pytest.mark.parametrize(
    "content",
    [
        b"",
        b"plain text",
        b"https://example.com/album",
        b"<album>",
        b"<artist/>",
        b'<album xmlns="urn:unknown"/>',
        b'<!DOCTYPE album [<!ENTITY x "expanded">]><album><title>&x;</title></album>',
        '<!DOCTYPE album SYSTEM "file:///etc/passwd"><album/>'.encode("utf-16"),
        b"<album><title><custom>keep</custom></title></album>",
        b"<album/>" + b" " * MAX_NFO_BYTES,
    ],
    ids=[
        "empty",
        "text",
        "url",
        "malformed",
        "wrong-root",
        "namespace",
        "entity",
        "utf16-dtd",
        "nested-title",
        "oversized",
    ],
)
def test_unsupported_documents_are_never_written(tmp_path, content):
    source = tmp_path / "album.nfo"
    source.write_bytes(content)
    with pytest.raises(TagWriteError):
        XmlAlbumNfoCodec().plan(source, VALUES)
    assert source.read_bytes() == content


def test_rich_artist_credits_reorder_without_reassigning_ids(tmp_path):
    target = change_xml(
        tmp_path,
        """<album>
<albumArtistCredits custom="keep"><artist>A</artist>
<musicBrainzArtistID>id-a</musicBrainzArtistID></albumArtistCredits>
<albumArtistCredits><artist>B</artist><musicBrainzArtistID>id-b</musicBrainzArtistID></albumArtistCredits>
</album>""",
        replace(VALUES, artists=("B", "A")),
    )
    doc = minidom.parse(str(target))
    credits = doc.getElementsByTagName("albumArtistCredits")
    assert [c.getElementsByTagName("artist")[0].firstChild.data for c in credits] == ["B", "A"]
    assert [c.getElementsByTagName("musicBrainzArtistID")[0].firstChild.data for c in credits] == [
        "id-b",
        "id-a",
    ]
    assert credits[1].getAttribute("custom") == "keep"


def test_rich_artist_replacement_is_conflict(tmp_path):
    source = tmp_path / "album.nfo"
    source.write_text(
        "<album><albumArtistCredits><artist>A</artist><musicBrainzArtistID>id-a</musicBrainzArtistID></albumArtistCredits></album>",
        encoding="utf-8",
    )
    with pytest.raises(TagWriteConflict, match="enriquecidos"):
        XmlAlbumNfoCodec().plan(source, VALUES)


@pytest.fixture
def album(setup_tags, tmp_path):
    database, repository, catalog, codec, files = setup_tags
    source = make_source(tmp_path, "flac")
    entry = repository.save(read_metadata(source), source.parent, source.name)
    nfo = source.parent / "album.nfo"
    nfo.write_text(
        "<album><title>Outdated</title><year>1990</year><review>Keep</review></album>",
        encoding="utf-8",
    )
    service = TagWriteService(catalog, codec, files, nfo_codec=XmlAlbumNfoCodec())
    return database, repository, source, entry, nfo, service


def prepare(service, database, ids):
    preview = service.previewer.execute(
        TagWriteRequest(database, ids, EDIT_FIELDS, allow_date_loss=True)
    )
    return replace(
        preview, nfo_items=service.nfo_writer.prepare(preview, lambda: False, lambda _: None)
    )


def test_nfo_only_operation_and_exact_idempotence(album):
    database, _, source, entry, nfo, service = album
    audio = source.read_bytes()
    report = service.execute(database, (entry.file_id,))
    assert report.results[0].state == "unchanged"
    assert report.nfo_results[0].state == "updated"
    assert report.nfo_results[0].published
    assert report.nfo_results[0].backup_path is None
    assert source.read_bytes() == audio
    assert xml_values(nfo, "title") == ["Old album"]
    assert xml_values(nfo, "year") == ["2020"]
    assert xml_values(nfo, "genre") == ["Metal"]
    assert "<review>Keep</review>" in nfo.read_text(encoding="utf-8")
    assert not (source.parent / ".trackfolio-backups").exists()
    original, stat = nfo.read_bytes(), nfo.stat()
    repeated = service.execute(database, (entry.file_id,))
    assert repeated.nfo_results[0].state == "unchanged"
    assert nfo.read_bytes() == original and nfo.stat().st_mtime_ns == stat.st_mtime_ns
    assert nfo.stat().st_ino == stat.st_ino
    journal = json.loads(report.journal_path.read_text(encoding="utf-8"))
    assert journal["schema"] == 2 and journal["closed"]


@pytest.mark.parametrize("alias_level", ["root", "ancestor"])
def test_nfo_uses_canonical_folder_for_imported_library_alias(album, tmp_path, alias_level):
    database, repository, source, _, nfo, service = album
    alias = tmp_path / "library-alias"
    try:
        alias.symlink_to(
            source.parent if alias_level == "root" else tmp_path, target_is_directory=True
        )
    except OSError:
        pytest.skip("Directory aliases unavailable")
    root = alias if alias_level == "root" else alias / source.parent.name
    entry = repository.save(read_metadata(source), root, source.name)
    report = service.execute(database, (entry.file_id,))
    assert report.results[0].state == "unchanged", report
    assert report.nfo_results[0].state == "updated", report
    assert report.nfo_results[0].path == nfo.resolve()
    assert xml_values(nfo, "title") == ["Old album"]
    loaded = service.files.load_journal(report.journal_path).preview
    assert loaded.nfo_items[0].library_root == root
    assert loaded.nfo_items[0].path == nfo.resolve()
    assert service.reviewer.execute(report.journal_path).nfo_results[0].state == "updated"
    assert service.execute(database, (entry.file_id,)).nfo_results[0].state == "unchanged"


def test_album_query_uses_portable_windows_root_stored_by_repository(album):
    database, repository, source, _, _, service = album

    class WindowsRoot(PureWindowsPath):
        # Exercise real Windows string/posix spellings against SQLite on any host.
        # Only physical resolution is mapped to the test's local music folder.
        def resolve(self):
            return source.parent.resolve()

    root = WindowsRoot("C:/Music/Música Ω")
    entry = repository.save(read_metadata(source), root, source.name)
    records = service.writer.catalog.album_tracks(database, root, source.parent)
    assert [record.file_id for record in records] == [entry.file_id]
    assert records[0].title == "Original"


def test_retargeted_library_alias_does_not_publish_nfo(album, tmp_path):
    database, repository, source, _, nfo, service = album
    alias = tmp_path / "library-alias"
    try:
        alias.symlink_to(source.parent, target_is_directory=True)
    except OSError:
        pytest.skip("Directory aliases unavailable")
    entry = repository.save(read_metadata(source), alias, source.name)
    preview = prepare(service, database, (entry.file_id,))
    original = nfo.read_bytes()
    other = tmp_path / "Other library"
    other.mkdir()
    alias.unlink()
    alias.symlink_to(other, target_is_directory=True)
    report = service.writer.execute(preview, ())
    assert report.nfo_results[0].state == "conflict", report
    assert nfo.read_bytes() == original
    assert not (other / "album.nfo").exists()


def test_directory_links_below_library_root_remain_blocked(album, tmp_path):
    database, repository, source, _, nfo, service = album
    root = tmp_path / "Library"
    root.mkdir()
    link = root / "Album"
    try:
        link.symlink_to(source.parent, target_is_directory=True)
    except OSError:
        pytest.skip("Directory aliases unavailable")
    entry = repository.save(read_metadata(source), root, "Album/" + source.name)
    original = nfo.read_bytes()
    report = service.execute(database, (entry.file_id,))
    assert report.nfo_results[0].state == "conflict", report
    assert nfo.read_bytes() == original


def test_service_repairs_old_joined_header_and_duplicate_credits_without_audio_changes(album):
    database, _, source, entry, nfo, service = album
    assert service.execute(database, (entry.file_id,)).nfo_results[0].state == "updated"
    original_audio = source.read_bytes()
    text = nfo.read_text(encoding="utf-8").replace("?>\n", "?>")
    text = text.replace(
        "</album>",
        "<artist>Artist</artist>"
        "<albumArtistCredits><artist>Artist</artist></albumArtistCredits></album>",
    )
    nfo.write_text(text, encoding="utf-8")
    report = service.execute(database, (entry.file_id,))
    assert report.results[0].state == "unchanged"
    assert report.nfo_results[0].state == "updated", report
    assert nfo.read_text(encoding="utf-8").startswith(
        '<?xml version="1.0" encoding="utf-8"?>\n<album>'
    )
    assert xml_values(nfo, "artist") == ["Artist"]
    assert "albumArtistCredits" not in nfo.read_text(encoding="utf-8")
    assert source.read_bytes() == original_audio
    assert service.execute(database, (entry.file_id,)).nfo_results[0].state == "unchanged"


@pytest.mark.parametrize("write_audio_first", [False, True])
def test_song_title_from_reported_nfo_updates_without_changing_album_or_duration(
    album, write_audio_first
):
    from mutagen.flac import FLAC

    database, repository, source, entry, nfo, service = album
    tags = FLAC(source)
    tags["TITLE"] = "To War!"
    tags["ALBUM"] = "Abbath"
    tags["ARTIST"] = "Abbath"
    tags["DATE"] = "2016"
    tags["GENRE"] = "Black Metal"
    tags.save()
    repository.save(read_metadata(source), source.parent, source.name)
    nfo.write_text(
        """<?xml version="1.0" encoding="utf-8"?><album>
  <title>Abbath</title><artist>Abbath</artist><year>2016</year>
  <releasedate>2016</releasedate><thumb>folder.jpg</thumb><genre>Black Metal</genre>
  <discnumber>01</discnumber><disctotal>01</disctotal><tracktotal>10</tracktotal>
  <track><position>1</position><title>To War!</title><duration>5:35</duration></track>
  <track><position>2</position><title>Winterbane</title><duration>6:50</duration></track>
</album>""",
        encoding="utf-8",
    )
    if write_audio_first:
        assert service.execute(database, (entry.file_id,)).nfo_results[0].state == "updated"
    edit(database, entry.file_id, title="To War!2")
    if write_audio_first:
        service_without_nfo = TagWriteService(
            service.writer.catalog, service.writer.codec, service.files
        )
        assert (
            service_without_nfo.execute(database, (entry.file_id,)).results[0].state == "confirmed"
        )
    report = service.execute(database, (entry.file_id,))
    assert report.nfo_results[0].state == "updated", report
    document = minidom.parse(str(nfo))
    tracks = document.getElementsByTagName("track")
    assert tracks[0].getElementsByTagName("title")[0].firstChild.data == "To War!2"
    assert tracks[0].getElementsByTagName("duration")[0].firstChild.data == "5:35"
    assert tracks[1].getElementsByTagName("title")[0].firstChild.data == "Winterbane"
    assert xml_values(nfo, "title") == ["Abbath"]
    assert xml_values(nfo, "thumb") == ["folder.jpg"]
    assert xml_values(nfo, "discnumber") == ["01"]
    assert read_metadata(source).title == "To War!2"
    assert service.execute(database, (entry.file_id,)).nfo_results[0].state == "unchanged"


def test_partial_selection_updates_only_selected_track_title(album):
    database, repository, source, entry, nfo, service = album
    second = source.with_name("b.flac")
    shutil.copyfile(source, second)
    other = repository.save(
        replace(read_metadata(second), track_number=2), second.parent, second.name
    )
    edit(database, entry.file_id, title="Selected correction")
    edit(database, other.file_id, title="Unpublished correction")
    nfo.write_text(
        """<album>
<track><position>1</position><title>First</title><duration>5:35</duration></track>
<track><position>2</position><title>Second</title><duration>6:50</duration></track>
</album>""",
        encoding="utf-8",
    )
    report = service.execute(database, (entry.file_id,))
    assert report.nfo_results[0].state == "updated", report
    document = minidom.parse(str(nfo))
    titles = [
        track.getElementsByTagName("title")[0].firstChild.data
        for track in document.getElementsByTagName("track")
    ]
    assert titles == ["Selected correction", "Second"]


def test_codec_disambiguates_same_position_by_disc_and_preserves_track_data(tmp_path):
    values = replace(
        VALUES,
        songs=(
            AlbumNfoSong(1, "First disc unchanged", 1, 1, False),
            AlbumNfoSong(2, "Second disc corrected", 1, 2, True),
        ),
    )
    target = change_xml(
        tmp_path,
        """<album>
<track><discnumber>01</discnumber><position>01</position><title>First</title><duration>1:23</duration></track>
<track custom="keep"><discnumber>02</discnumber><position>01</position>
<title sort="keep">Second<!--keep--></title><duration>4:56</duration><unknown>keep</unknown></track>
</album>""",
        values,
    )
    text = target.read_text(encoding="utf-8")
    assert "<title>First</title>" in text
    assert '<title sort="keep"><!--keep-->Second disc corrected</title>' in text
    assert "<duration>4:56</duration><unknown>keep</unknown>" in text
    assert "<discnumber>02</discnumber><position>01</position>" in text
    assert 'custom="keep"' in text


@pytest.mark.parametrize("position", [None, 1, 3])
def test_unmatched_or_ambiguous_track_titles_are_conflicts(tmp_path, position):
    source = tmp_path / "album.nfo"
    source.write_text(
        """<album><title>Keep</title>
<track><position>1</position><title>First</title></track>
<track><position>1</position><title>Duplicate</title></track></album>""",
        encoding="utf-8",
    )
    original = source.read_bytes()
    values = replace(VALUES, songs=(AlbumNfoSong(1, "Correction", position, 1, True),))
    with pytest.raises(TagWriteConflict):
        XmlAlbumNfoCodec().plan(source, values)
    assert source.read_bytes() == original


def test_duplicate_catalogue_positions_do_not_overwrite_one_xml_track(tmp_path):
    source = tmp_path / "album.nfo"
    source.write_text(
        "<album><track><position>1</position><title>Keep</title></track></album>", encoding="utf-8"
    )
    values = replace(
        VALUES,
        songs=(
            AlbumNfoSong(1, "Selected", 1, 1, True),
            AlbumNfoSong(2, "Unselected", 1, 2, False),
        ),
    )
    with pytest.raises(TagWriteConflict, match="Varias canciones"):
        XmlAlbumNfoCodec().plan(source, values)


def test_clearing_song_title_preserves_position_and_duration(tmp_path):
    target = change_xml(
        tmp_path,
        "<album><track><position>1</position><title>Old</title><duration>5:35</duration></track></album>",
        replace(VALUES, songs=(AlbumNfoSong(1, None, 1, None, True),)),
    )
    track = minidom.parse(str(target)).getElementsByTagName("track")[0]
    assert not track.getElementsByTagName("title")
    assert track.getElementsByTagName("position")[0].firstChild.data == "1"
    assert track.getElementsByTagName("duration")[0].firstChild.data == "5:35"


def test_previous_version_two_nfo_journal_without_song_fields_is_readable(album):
    database, _, _, entry, _, service = album
    report = service.execute(database, (entry.file_id,))
    data = json.loads(report.journal_path.read_text(encoding="utf-8"))
    for nfo in data["preview"]["nfo_items"]:
        nfo["values"].pop("songs")
        for track in nfo["tracks"]:
            for key in ("title", "track_number", "disc_number"):
                track.pop(key)
    report.journal_path.write_text(json.dumps(data), encoding="utf-8")
    loaded = service.files.load_journal(report.journal_path).preview
    assert loaded.nfo_items[0].values.songs == ()
    assert loaded.nfo_items[0].tracks[0].title is None
    assert service.reviewer.execute(report.journal_path).nfo_results[0].state == "updated"


def test_absence_is_success_and_does_not_create_nfo(album):
    database, _, _, entry, nfo, service = album
    nfo.unlink()
    report = service.execute(database, (entry.file_id,))
    assert report.nfo_results[0].state == "absent" and not nfo.exists()
    assert not report.fatal_error


def test_subset_uses_all_folder_tracks_without_writing_unselected_audio(album, monkeypatch):
    database, repository, source, entry, nfo, service = album
    second = source.with_name("b.flac")
    shutil.copyfile(source, second)
    other = repository.save(read_metadata(second), second.parent, second.name)
    edit(database, other.file_id, genres=("Rock", "Metal"), title="Not published")
    edit(database, entry.file_id, title="Publish this")
    untouched = second.read_bytes()
    report = service.execute(database, (entry.file_id,))
    assert report.results[0].state == "confirmed"
    assert report.nfo_results[0].state == "updated"
    assert xml_values(nfo, "genre") == ["Metal", "Rock"]
    assert second.read_bytes() == untouched
    assert len(report.results) == 1


def test_shared_nfo_is_written_once(album, monkeypatch):
    database, repository, source, entry, nfo, service = album
    second = source.with_name("b.flac")
    shutil.copyfile(source, second)
    other = repository.save(read_metadata(second), second.parent, second.name)
    calls = []
    publish = service.files.publish

    def observe(item, temporary):
        calls.append(item.path)
        publish(item, temporary)

    monkeypatch.setattr(service.files, "publish", observe)
    report = service.execute(database, (entry.file_id, other.file_id))
    assert report.nfo_results[0].state == "updated" and calls == [nfo]


@pytest.mark.parametrize("field,value", [("album", "Other"), ("album_year", 2000)])
def test_disagreement_preserves_whole_nfo(album, field, value):
    database, repository, source, entry, nfo, service = album
    second = source.with_name("b.flac")
    shutil.copyfile(source, second)
    other = repository.save(read_metadata(second), second.parent, second.name)
    edit(database, other.file_id, **{field: value})
    original = nfo.read_bytes()
    report = service.execute(database, (entry.file_id,))
    assert report.nfo_results[0].state == "conflict"
    assert nfo.read_bytes() == original
    assert not json.loads(report.journal_path.read_text(encoding="utf-8"))["closed"]


def test_uncatalogued_audio_is_conflict(album):
    database, _, source, entry, nfo, service = album
    shutil.copyfile(source, source.with_name("unimported.MP3"))
    original = nfo.read_bytes()
    report = service.execute(database, (entry.file_id,))
    assert report.nfo_results[0].state == "conflict"
    assert nfo.read_bytes() == original


def test_compilation_preserves_existing_credits(album):
    database, repository, source, entry, nfo, service = album
    second = source.with_name("b.flac")
    shutil.copyfile(source, second)
    other = repository.save(read_metadata(second), second.parent, second.name)
    edit(database, other.file_id, artists=("Different",))
    nfo.write_text(
        "<album><albumArtistCredits><artist>Various</artist><musicBrainzArtistID>keep</musicBrainzArtistID></albumArtistCredits></album>",
        encoding="utf-8",
    )
    report = service.execute(database, (entry.file_id,))
    assert report.nfo_results[0].state == "updated"
    assert (
        "<artist>Various</artist><musicBrainzArtistID>keep</musicBrainzArtistID>"
        in nfo.read_text(encoding="utf-8")
    )


@pytest.mark.parametrize("mutation", ["nfo", "appears", "disappears", "catalog", "folder"])
def test_concurrent_changes_are_conflicts(album, mutation):
    database, _, source, entry, nfo, service = album
    if mutation == "appears":
        nfo.unlink()
    preview = prepare(service, database, (entry.file_id,))
    if mutation in ("nfo", "appears"):
        nfo.write_text("<album><review>External change</review></album>", encoding="utf-8")
    elif mutation == "disappears":
        nfo.unlink()
    elif mutation == "catalog":
        edit(database, entry.file_id, album="Concurrent album")
    else:
        shutil.copyfile(source, source.with_name("new.flac"))
    current = nfo.read_bytes() if nfo.exists() else None
    report = service.writer.execute(preview, ())
    assert report.nfo_results[0].state in ("conflict", "failed")
    assert (nfo.read_bytes() if nfo.exists() else None) == current


@pytest.mark.parametrize("kind", ["symlink", "hardlink", "readonly"])
def test_unsafe_nfo_is_preserved(album, kind, tmp_path):
    database, _, _, entry, nfo, service = album
    content = nfo.read_bytes()
    if kind == "readonly":
        nfo.chmod(0o444)
    else:
        other = tmp_path / "external.nfo"
        other.write_bytes(content)
        nfo.unlink()
        try:
            if kind == "symlink":
                nfo.symlink_to(other)
            else:
                os.link(other, nfo)
        except OSError:
            pytest.skip("Links unavailable")
    try:
        report = service.execute(database, (entry.file_id,))
        assert report.nfo_results[0].state in ("failed", "conflict")
        assert nfo.read_bytes() == content
    finally:
        if kind == "readonly":
            nfo.chmod(0o644)


def test_audio_failure_leaves_nfo_pending_and_backup_available(album, monkeypatch):
    database, _, _, entry, nfo, service = album
    edit(database, entry.file_id, title="New title")
    original = nfo.read_bytes()

    def fail(*args):
        raise OSError("audio failure")

    monkeypatch.setattr(service.writer.codec, "write_verified", fail)
    report = service.execute(database, (entry.file_id,))
    assert report.results[0].state == "failed" and report.results[0].backup_path.is_file()
    assert report.nfo_results[0].state == "pending" and nfo.read_bytes() == original


def test_nfo_failure_keeps_audio_result_backups_and_allows_retry(album, monkeypatch):
    database, _, source, entry, nfo, service = album
    edit(database, entry.file_id, title="New title")
    codec = service.nfo_writer.codec
    write = codec.write_verified
    original = nfo.read_bytes()

    def fail(*args):
        raise OSError("NFO failure")

    monkeypatch.setattr(codec, "write_verified", fail)
    report = service.execute(database, (entry.file_id,))
    assert report.results[0].state == "confirmed"
    assert report.nfo_results[0].state == "failed" and nfo.read_bytes() == original
    assert report.results[0].backup_path.is_file() and report.nfo_results[0].backup_path.is_file()
    assert read_metadata(source).title == "New title"
    monkeypatch.setattr(codec, "write_verified", write)
    retry = service.execute(database, (entry.file_id,))
    assert retry.results[0].state == "unchanged" and retry.nfo_results[0].state == "updated"
    assert not (source.parent / ".trackfolio-backups").exists()


def test_cancel_before_nfo_publication_preserves_original(album, monkeypatch):
    database, _, _, entry, nfo, service = album
    cancel = False
    codec = service.nfo_writer.codec
    write = codec.write_verified

    def stop(*args):
        nonlocal cancel
        write(*args)
        cancel = True

    monkeypatch.setattr(codec, "write_verified", stop)
    original = nfo.read_bytes()
    report = service.execute(database, (entry.file_id,), is_cancelled=lambda: cancel)
    assert report.cancelled and report.nfo_results[0].state == "pending"
    assert nfo.read_bytes() == original and report.nfo_results[0].backup_path.is_file()


def test_error_after_nfo_replace_is_reported_as_published_and_reviewable(album, monkeypatch):
    database, _, _, entry, nfo, service = album
    publish = service.files.publish

    def fail_after(item, temporary):
        publish(item, temporary)
        raise TagPublishedError("sync failure")

    monkeypatch.setattr(service.files, "publish", fail_after)
    report = service.execute(database, (entry.file_id,))
    assert report.nfo_results[0].state == "failed" and report.nfo_results[0].published
    assert xml_values(nfo, "title") == ["Old album"]
    reviewed = service.reviewer.execute(report.journal_path, reconcile=True)
    assert reviewed.nfo_results[0].state == "updated" and reviewed.nfo_results[0].published


def test_space_reservation_includes_nfo_before_writing(album, monkeypatch):
    database, _, _, entry, nfo, service = album
    original = nfo.read_bytes()
    from trackfolio.infrastructure import tag_write_files

    monkeypatch.setattr(
        tag_write_files.shutil, "disk_usage", lambda _: shutil._ntuple_diskusage(1, 1, 0)
    )
    report = service.execute(database, (entry.file_id,))
    assert report.fatal_error and report.nfo_results[0].state == "pending"
    assert nfo.read_bytes() == original


def test_old_journal_is_still_readable(album):
    database, _, _, entry, _, service = album
    preview = service.previewer.execute(TagWriteRequest(database, (entry.file_id,), EDIT_FIELDS))
    journal = service.files.journal(preview)
    data = json.loads(journal.path.read_text(encoding="utf-8"))
    data["schema"] = 1
    data.pop("nfos")
    data["preview"].pop("nfo_items")
    journal.path.write_text(json.dumps(data), encoding="utf-8")
    loaded = service.files.load_journal(journal.path)
    assert loaded.preview.nfo_items == ()
    assert service.reviewer.execute(journal.path).nfo_results == ()


def test_review_detects_external_nfo_changes(album):
    database, _, _, entry, nfo, service = album
    report = service.execute(database, (entry.file_id,))
    nfo.write_text("<album><review>External</review></album>", encoding="utf-8")
    reviewed = service.reviewer.execute(report.journal_path, reconcile=True)
    assert reviewed.nfo_results[0].state == "conflict"
    assert not json.loads(report.journal_path.read_text(encoding="utf-8"))["closed"]


def test_audio_date_confirmation_does_not_invalidate_album_values(album):
    database, _, source, entry, nfo, service = album
    edit(database, entry.file_id, album="Correct album", album_year=2021)
    nfo.write_text("<album><releasedate>2020-02-29</releasedate></album>", encoding="utf-8")
    report = service.execute(database, (entry.file_id,))
    assert report.results[0].state == "confirmed", report
    assert report.nfo_results[0].state == "updated", report
    assert read_metadata(source).album_year == 2021
    assert xml_values(nfo, "releasedate") == ["2021"]


def test_album_artist_credits_override_track_artist_fallback(album):
    database, repository, source, entry, nfo, service = album
    repository.save(
        replace(read_metadata(source), album_artists=("Album artist",)), source.parent, source.name
    )
    nfo.write_text("<album><title>Old</title><artist>Old</artist></album>", encoding="utf-8")
    report = service.execute(database, (entry.file_id,))
    assert report.nfo_results[0].state == "updated"
    assert "<artist>Album artist</artist>" in nfo.read_text(encoding="utf-8")
    assert "<artist>Artist</artist>" not in nfo.read_text(encoding="utf-8")


def test_conflicting_album_credits_are_not_guessed(album):
    database, repository, source, entry, nfo, service = album
    second = source.with_name("b.flac")
    shutil.copyfile(source, second)
    repository.save(
        replace(read_metadata(second), album_artists=("Different",)), second.parent, second.name
    )
    original = nfo.read_bytes()
    report = service.execute(database, (entry.file_id,))
    assert report.nfo_results[0].state == "conflict"
    assert nfo.read_bytes() == original


def test_other_albums_continue_and_backups_are_kept_on_any_nfo_failure(album, tmp_path):
    database, repository, source, entry, nfo, service = album
    other_root = tmp_path / "Other album"
    other_root.mkdir()
    second = other_root / "b.flac"
    shutil.copyfile(source, second)
    other = repository.save(read_metadata(second), other_root, second.name)
    other_nfo = other_root / "album.nfo"
    other_nfo.write_text("<album/>", encoding="utf-8")
    nfo.write_text("broken XML", encoding="utf-8")
    edit(database, entry.file_id, title="First")
    edit(database, other.file_id, title="Second")
    report = service.execute(database, (entry.file_id, other.file_id))
    assert [r.state for r in report.results] == ["confirmed", "confirmed"]
    by_path = {r.path: r for r in report.nfo_results}
    assert by_path[nfo].state == "failed" and by_path[other_nfo].state == "updated"
    assert by_path[other_nfo].backup_path.is_file()
    assert all(result.backup_path.is_file() for result in report.results)
    assert nfo.read_text(encoding="utf-8") == "broken XML"


@pytest.mark.parametrize("stage", ["temporary_verified", "written", "updated"])
def test_journal_failure_keeps_backups_and_reports_actual_publication(album, monkeypatch, stage):
    from trackfolio.infrastructure.tag_write_files import FileTagJournal

    database, _, _, entry, nfo, service = album
    record = FileTagJournal.record_nfo
    failed = False

    def fail_once(self, item, state, **details):
        nonlocal failed
        if state == stage and not failed:
            failed = True
            raise OSError("journal unavailable")
        return record(self, item, state, **details)

    monkeypatch.setattr(FileTagJournal, "record_nfo", fail_once)
    original = nfo.read_bytes()
    report = service.execute(database, (entry.file_id,))
    result = report.nfo_results[0]
    assert result.state == "failed" and result.backup_path.is_file()
    assert result.published == (stage != "temporary_verified")
    assert (nfo.read_bytes() != original) == result.published
    reviewed = service.reviewer.execute(report.journal_path, reconcile=True)
    assert reviewed.nfo_results[0].state == (
        "pending" if stage == "temporary_verified" else "updated"
    )


def test_nfo_write_preserves_file_mode_and_extended_attributes(album):
    database, _, _, entry, nfo, service = album
    nfo.chmod(0o640)
    before_mode = nfo.stat().st_mode
    xattr = False
    if hasattr(os, "setxattr"):
        try:
            os.setxattr(nfo, "user.trackfolio-nfo", b"keep")
            xattr = True
        except OSError:
            pass
    report = service.execute(database, (entry.file_id,))
    assert report.nfo_results[0].state == "updated", report
    assert nfo.stat().st_mode == before_mode
    if xattr:
        assert os.getxattr(nfo, "user.trackfolio-nfo") == b"keep"


def test_does_not_search_for_nfo_above_audio_folder(album):
    database, _, source, entry, nfo, service = album
    higher = source.parent.parent / "album.nfo"
    nfo.rename(higher)
    original = higher.read_bytes()
    report = service.execute(database, (entry.file_id,))
    assert report.nfo_results[0].state == "absent"
    assert higher.read_bytes() == original and not nfo.exists()


def test_nested_album_under_imported_root_and_sql_wildcards(setup_tags, tmp_path):
    database, repository, catalog, codec, files = setup_tags
    root = tmp_path / "Library"
    folder = root / "Artist" / "100%_Ω"
    folder.mkdir(parents=True)
    source = folder / "a.flac"
    template = make_source(tmp_path, "flac")
    shutil.copyfile(template, source)
    entry = repository.save(read_metadata(source), root, source.relative_to(root).as_posix())
    subfolder = folder / "unrelated"
    subfolder.mkdir()
    other = subfolder / "b.flac"
    shutil.copyfile(template, other)
    repository.save(
        replace(read_metadata(other), album="Different"), root, other.relative_to(root).as_posix()
    )
    nfo = folder / "album.nfo"
    nfo.write_text("<album/>", encoding="utf-8")
    report = TagWriteService(catalog, codec, files, XmlAlbumNfoCodec()).execute(
        database, (entry.file_id,)
    )
    assert report.nfo_results[0].state == "updated", report
    assert xml_values(nfo, "title") == ["Old album"]


@pytest.mark.parametrize("stage", ["temporary_verified", "written"])
def test_real_process_interruption_reviews_nfo_without_rewriting(album, stage):
    import subprocess
    import sys
    import textwrap

    database, _, _, entry, nfo, service = album
    original = nfo.read_bytes()
    program = textwrap.dedent("""
        import os, sys
        from pathlib import Path
        from trackfolio.application.write_tags import TagWriteService
        from trackfolio.infrastructure.album_nfo import XmlAlbumNfoCodec
        from trackfolio.infrastructure.tag_write import MutagenTagCodec
        from trackfolio.infrastructure.tag_write_catalog import SqliteTagCatalog
        from trackfolio.infrastructure.tag_write_files import FileTagAccess, FileTagJournal
        database, file_id, root, stage = sys.argv[1:]
        record = FileTagJournal.record_nfo
        def checkpoint(self, item, state, **details):
            if state == stage:
                os._exit(73)
            return record(self, item, state, **details)
        FileTagJournal.record_nfo = checkpoint
        TagWriteService(SqliteTagCatalog(), MutagenTagCodec(), FileTagAccess(Path(root)),
                        XmlAlbumNfoCodec()).execute(Path(database), (int(file_id),))
    """)
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            program,
            str(database),
            str(entry.file_id),
            str(service.files.journal_root),
            stage,
        ],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 73, result.stdout + result.stderr
    pending = service.files.pending()
    assert len(pending) == 1
    content = nfo.read_bytes()
    assert (content != original) == (stage == "written")
    reviewed = service.reviewer.execute(pending[0].journal_path, reconcile=True)
    assert reviewed.nfo_results[0].state == ("updated" if stage == "written" else "pending")
    assert nfo.read_bytes() == content
    assert reviewed.nfo_results[0].backup_path.is_file()
