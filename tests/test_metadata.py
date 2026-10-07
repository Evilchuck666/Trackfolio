"""Synthetic containers exercise real Mutagen parsing without storing music fixtures."""

from __future__ import annotations

import binascii
import hashlib
import struct
import zlib
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest
from mutagen.id3 import (
    APIC,
    ID3,
    TALB,
    TCON,
    TDRC,
    TIT2,
    TPE1,
    TPE2,
    TPOS,
    TRCK,
    TXXX,
    USLT,
)

from trackfolio.domain.metadata import RawTagValue, TrackMetadata
from trackfolio.infrastructure.metadata import (
    MetadataReadError,
    UnsupportedAudioError,
    read_metadata,
)


def png(width=1, height=1, color=(255, 0, 0)):
    def chunk(name, payload):
        return (
            struct.pack(">I", len(payload))
            + name
            + payload
            + struct.pack(">I", binascii.crc32(name + payload))
        )

    rows = b"".join(b"\x00" + bytes(color) * width for _ in range(height))
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(rows))
        + chunk(b"IEND", b"")
    )


def write_flac(path, tags=None, pictures=()):
    # A metadata-only FLAC fixture: no audio content or copyrighted material.
    properties = (44100 << 44) | (1 << 41) | (15 << 36) | 88200
    stream_info = b"\x10\x00\x10\x00" + b"\x00" * 6 + properties.to_bytes(8, "big") + b"\x00" * 16
    blocks = [(0, stream_info)]
    if tags is not None:
        vendor = b"Trackfolio tests"
        payload = struct.pack("<I", len(vendor)) + vendor + struct.pack("<I", len(tags))
        for key, value in tags:
            comment = f"{key}={value}".encode()
            payload += struct.pack("<I", len(comment)) + comment
        blocks.append((4, payload))
    for picture_type, image in pictures:
        mime = b"image/png"
        payload = (
            struct.pack(">II", picture_type, len(mime))
            + mime
            + struct.pack(">I", 0)
            + struct.pack(">IIIII", 1, 1, 24, 0, len(image))
            + image
        )
        blocks.append((6, payload))
    content = b"fLaC"
    for index, (block_type, payload) in enumerate(blocks):
        code = block_type | (0x80 if index == len(blocks) - 1 else 0)
        content += bytes([code]) + len(payload).to_bytes(3, "big") + payload
    path.write_bytes(content)
    return path


def write_mp3(path, tags=None):
    # MPEG-1 layer III header plus synthetic frame payloads, parsed but never played.
    frame = b"\xff\xfb\x90\x64" + b"\x00" * 413
    path.write_bytes(frame * 8)
    if tags is not None:
        tags.save(path)
    return path


@pytest.mark.parametrize("tags", [None, []])
def test_missing_tags_stay_missing_and_do_not_invent_filename_title(tmp_path, tags):
    metadata = read_metadata(write_flac(tmp_path / "03 - Filename is not the title.flac", tags))
    assert metadata.title is None
    assert metadata.album is None
    assert metadata.album_year is None and metadata.album_date is None
    assert metadata.track_number is None and metadata.track_total is None
    assert metadata.disc_number is None and metadata.disc_total is None
    assert metadata.artists == metadata.album_artists == metadata.genres == ()
    assert metadata.lyrics is None and metadata.artwork is None
    assert metadata.raw_tags == ()
    assert metadata.audio_format == "flac"
    assert metadata.duration_seconds == pytest.approx(2)
    assert (metadata.sample_rate_hz, metadata.channels, metadata.bits_per_sample) == (44100, 2, 16)


def test_multivalued_text_and_original_unknown_tags_are_preserved(tmp_path):
    tags = [
        ("TITLE", "Título de prueba"),
        ("ARTIST", "AC/DC"),
        ("ARTIST", "Otro artista"),
        ("GENRE", "Heavy Metal"),
        ("GENRE", "Rock"),
        ("CUSTOM_TAG", "  keep whitespace  "),
        ("CUSTOM_TAG", ""),
        ("LYRICS", "Line one\nLine two\n"),
    ]
    metadata = read_metadata(write_flac(tmp_path / "track.flac", tags))
    assert metadata.title == "Título de prueba"
    assert metadata.artists == ("AC/DC", "Otro artista")
    assert metadata.album_artists == ()
    assert metadata.genres == ("Heavy Metal", "Rock")
    assert metadata.lyrics == "Line one\nLine two\n"
    assert metadata.raw_tags == (
        RawTagValue("TITLE", "Título de prueba", 0),
        RawTagValue("ARTIST", "AC/DC", 0),
        RawTagValue("ARTIST", "Otro artista", 1),
        RawTagValue("GENRE", "Heavy Metal", 0),
        RawTagValue("GENRE", "Rock", 1),
        RawTagValue("CUSTOM_TAG", "  keep whitespace  ", 0),
        RawTagValue("CUSTOM_TAG", "", 1),
        RawTagValue("LYRICS", "Line one\nLine two\n", 0),
    )


def test_fractional_track_disc_numbers_and_separate_totals(tmp_path):
    metadata = read_metadata(
        write_flac(
            tmp_path / "track.flac",
            [
                ("TRACKNUMBER", "03/10"),
                ("TOTALTRACKS", "12"),
                ("DISCNUMBER", " 01 / 02 "),
                ("TOTALDISCS", "03"),
            ],
        )
    )
    assert (metadata.track_number, metadata.track_total) == (3, 12)
    assert (metadata.disc_number, metadata.disc_total) == (1, 3)


@pytest.mark.parametrize("number", ["bad", "-3", "0", "1/2/3", "1.5", "３"])
def test_malformed_numbers_remain_none_and_keep_the_original_tag(tmp_path, number):
    metadata = read_metadata(
        write_flac(
            tmp_path / "track.flac",
            [
                ("TRACKNUMBER", number),
                ("DISCNUMBER", number),
            ],
        )
    )
    assert metadata.track_number is None and metadata.disc_number is None
    assert metadata.track_total is None and metadata.disc_total is None
    assert metadata.raw_tags[0].value == number


@pytest.mark.parametrize(
    ("value", "year"),
    [
        ("1981", 1981),
        ("1981-05", 1981),
        ("1981-05-03", 1981),
        ("1981-05-03T12:30:00Z", 1981),
        ("1981-99-99", None),
        ("1981-not-a-date", None),
        ("unknown", None),
        ("0000", None),
    ],
)
def test_date_year_normalization_keeps_the_original_date(tmp_path, value, year):
    metadata = read_metadata(write_flac(tmp_path / "track.flac", [("DATE", value)]))
    assert metadata.album_date == value
    assert metadata.album_year == year
    assert metadata.raw_tags == (RawTagValue("DATE", value, 0),)


def test_valid_front_cover_wins_over_first_picture_and_folder_fallback(tmp_path):
    back, front, folder = png(color=(0, 0, 255)), png(2, 3), png(color=(0, 255, 0))
    (tmp_path / "album.jpg").write_bytes(folder)
    metadata = read_metadata(
        write_flac(
            tmp_path / "track.flac",
            pictures=[
                (4, back),
                (3, b"broken front cover"),
                (3, front),
            ],
        )
    )
    assert metadata.artwork is not None
    assert metadata.artwork.data == front
    assert metadata.artwork.source == "embedded" and metadata.artwork.source_path is None
    assert (metadata.artwork.mime_type, metadata.artwork.width, metadata.artwork.height) == (
        "image/png",
        2,
        3,
    )


def test_first_valid_picture_is_used_when_there_is_no_valid_front_cover(tmp_path):
    back, other = png(color=(0, 0, 255)), png(color=(0, 255, 0))
    metadata = read_metadata(
        write_flac(
            tmp_path / "track.flac",
            pictures=[
                (3, b"broken"),
                (4, back),
                (0, other),
            ],
        )
    )
    assert metadata.artwork is not None and metadata.artwork.data == back


def test_album_jpg_is_used_after_invalid_embedded_artwork(tmp_path):
    cover = tmp_path / "album.jpg"
    image = png(3, 2)
    cover.write_bytes(image)
    metadata = read_metadata(write_flac(tmp_path / "track.flac", pictures=[(3, b"broken")]))
    assert metadata.artwork is not None
    assert metadata.artwork.data == image
    assert metadata.artwork.source == "album.jpg"
    assert metadata.artwork.source_path == cover.resolve()


def test_other_folder_image_names_are_not_used(tmp_path):
    (tmp_path / "cover.jpg").write_bytes(png())
    (tmp_path / "folder.jpg").write_bytes(png())
    metadata = read_metadata(write_flac(tmp_path / "track.flac"))
    assert metadata.artwork is None


@pytest.mark.parametrize("failure", ["corrupt", "unreadable"])
def test_optional_folder_artwork_failure_does_not_fail_audio_import(tmp_path, monkeypatch, failure):
    path = write_flac(tmp_path / "track.flac", [("TITLE", "Still readable")])
    cover = tmp_path / "album.jpg"
    cover.write_bytes(b"not an image" if failure == "corrupt" else png())
    if failure == "unreadable":
        original = Path.read_bytes

        def guarded_read(self):
            if self == cover:
                raise PermissionError("Unreadable artwork")
            return original(self)

        monkeypatch.setattr(Path, "read_bytes", guarded_read)
    metadata = read_metadata(path)
    assert metadata.title == "Still readable" and metadata.artwork is None


def test_mp3_id3_metadata_multivalues_lyrics_and_embedded_cover(tmp_path):
    tags = ID3()
    for frame in [
        TIT2(encoding=3, text=["Título MP3"]),
        TALB(encoding=3, text=["Album MP3"]),
        TPE1(encoding=3, text=["AC/DC", "Second artist"]),
        TPE2(encoding=3, text=["Album artist"]),
        TCON(encoding=3, text=["Rock", "Metal"]),
        TRCK(encoding=3, text=["03/10"]),
        TPOS(encoding=3, text=["01/02"]),
        TDRC(encoding=3, text=["1981-05-03"]),
        USLT(encoding=3, lang="eng", desc="", text="Lyrics\nsecond line"),
        TXXX(encoding=3, desc="unknown", text=["first", "second"]),
        APIC(encoding=3, mime="image/png", type=3, desc="front", data=png()),
    ]:
        tags.add(frame)
    metadata = read_metadata(write_mp3(tmp_path / "track.mp3", tags))
    assert metadata.audio_format == "mp3"
    assert metadata.title == "Título MP3" and metadata.album == "Album MP3"
    assert metadata.artists == ("AC/DC", "Second artist")
    assert metadata.album_artists == ("Album artist",)
    assert metadata.genres == ("Rock", "Metal")
    assert metadata.album_year == 1981 and metadata.album_date == "1981-05-03"
    assert (metadata.track_number, metadata.track_total) == (3, 10)
    assert (metadata.disc_number, metadata.disc_total) == (1, 2)
    assert metadata.lyrics == "Lyrics\nsecond line"
    assert metadata.artwork is not None and metadata.artwork.data == png()
    assert metadata.bits_per_sample is None
    assert [tag.value for tag in metadata.raw_tags if tag.key == "TXXX:unknown"] == [
        "first",
        "second",
    ]


def test_mp3_without_id3_tags_is_valid(tmp_path):
    metadata = read_metadata(write_mp3(tmp_path / "track.mp3"))
    assert metadata.audio_format == "mp3"
    assert metadata.title is None and metadata.artists == () and metadata.raw_tags == ()


def test_format_is_detected_from_content_instead_of_filename_extension(tmp_path):
    metadata = read_metadata(write_flac(tmp_path / "misnamed.mp3", [("TITLE", "Actually FLAC")]))
    assert metadata.audio_format == "flac" and metadata.title == "Actually FLAC"
    metadata = read_metadata(write_mp3(tmp_path / "misnamed.flac"))
    assert metadata.audio_format == "mp3"


def test_audio_file_is_unchanged_after_reading_metadata(tmp_path):
    path = write_flac(tmp_path / "read-only.flac", [("TITLE", "Keep this file unchanged")])
    expected_hash = hashlib.sha256(path.read_bytes()).digest()
    expected_mtime = path.stat().st_mtime_ns
    path.chmod(0o444)
    try:
        metadata = read_metadata(path)
        assert metadata.title == "Keep this file unchanged"
        assert hashlib.sha256(path.read_bytes()).digest() == expected_hash
        assert path.stat().st_mtime_ns == expected_mtime
    finally:
        path.chmod(0o644)


def test_missing_and_unsupported_files_produce_adapter_errors(tmp_path):
    with pytest.raises(MetadataReadError, match="No se pueden leer"):
        read_metadata(tmp_path / "missing.flac")
    path = tmp_path / "unsupported.bin"
    path.write_bytes(b"not an audio container")
    with pytest.raises(UnsupportedAudioError):
        read_metadata(path)


def test_metadata_values_cannot_be_mutated():
    metadata = TrackMetadata(title="Original", artists=("Artist",))
    with pytest.raises(FrozenInstanceError):
        metadata.title = "Changed"
