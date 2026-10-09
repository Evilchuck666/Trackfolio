"""Recorridos temporales del explorador, sin música del usuario."""

from pathlib import Path

import pytest

from trackfolio.application.import_catalog import AudioScanError
from trackfolio.infrastructure import audio_scan
from trackfolio.infrastructure.audio_scan import FileSystemAudioScanner


def scan(root, is_cancelled=lambda: False, on_discovered=lambda _: None):
    return FileSystemAudioScanner().scan(root, is_cancelled, on_discovered)


def test_recursive_candidates_are_sorted_and_ignore_other_files_and_links(tmp_path):
    album = tmp_path / "Álbum con espacios"
    album.mkdir()
    for path in (tmp_path / "Z.MP3", album / "02.FLAC", album / "01.mp3"):
        path.touch()
    (tmp_path / "ignored.ogg").touch()
    (tmp_path / "empty directory").mkdir()
    outside = tmp_path.parent / "outside.mp3"
    outside.touch()
    try:
        (tmp_path / "link.mp3").symlink_to(outside)
        (tmp_path / "loop").symlink_to(tmp_path, target_is_directory=True)
    except OSError:
        pass  # Windows may not grant permission to create symbolic links.
    discovered = []
    result = scan(tmp_path, on_discovered=discovered.append)
    assert [source.relative_path for source in result.sources] == [
        "Z.MP3",
        "Álbum con espacios/01.mp3",
        "Álbum con espacios/02.FLAC",
    ]
    assert all(source.path == tmp_path / source.relative_path for source in result.sources)
    assert discovered == [1, 2, 3]
    assert result.completed and result.issues == ()


def test_junction_is_not_traversed(tmp_path, monkeypatch):
    junction = tmp_path / "junction"
    junction.mkdir()
    (junction / "other.flac").touch()
    (tmp_path / "keep.mp3").touch()
    monkeypatch.setattr(Path, "is_junction", lambda path: path == junction)
    assert [source.relative_path for source in scan(tmp_path).sources] == ["keep.mp3"]


def test_subdirectory_failure_is_an_issue_but_root_failure_is_fatal(tmp_path, monkeypatch):
    unreadable = tmp_path / "unreadable"
    unreadable.mkdir()
    (tmp_path / "keep.flac").touch()
    original = audio_scan.os.scandir

    def fail_subdirectory(path):
        if Path(path) == unreadable:
            raise PermissionError("denied")
        return original(path)

    monkeypatch.setattr(audio_scan.os, "scandir", fail_subdirectory)
    result = scan(tmp_path)
    assert len(result.sources) == 1
    assert result.completed
    assert len(result.issues) == 1
    assert result.issues[0].path == unreadable
    assert result.issues[0].stage == "scan"

    def fail_root(_):
        raise PermissionError("denied")

    monkeypatch.setattr(audio_scan.os, "scandir", fail_root)
    with pytest.raises(AudioScanError, match="explorar"):
        scan(tmp_path)


def test_cancelled_discovery_returns_partial_candidates_with_unknown_total(tmp_path):
    for name in ("a.flac", "b.mp3", "c.mp3"):
        (tmp_path / name).touch()
    discovered = []
    result = scan(tmp_path, lambda: bool(discovered), discovered.append)
    assert not result.completed
    assert [source.relative_path for source in result.sources] == ["a.flac"]
    assert discovered == [1]
    assert scan(tmp_path, lambda: True).sources == ()


def test_regular_file_inspection_failure_is_reported(tmp_path, monkeypatch):
    (tmp_path / "keep.flac").touch()

    def failed_junction(_):
        raise OSError("source disappeared")

    monkeypatch.setattr(Path, "is_junction", failed_junction)
    result = scan(tmp_path)
    assert result.sources == () and result.completed
    assert len(result.issues) == 1
    assert result.issues[0].stage == "scan"


def test_directory_replaced_by_link_after_discovery_is_not_traversed(tmp_path, monkeypatch):
    child = tmp_path / "child"
    child.mkdir()
    (child / "outside.flac").touch()
    original = Path.is_junction
    inspections = 0

    def replaced(path):
        nonlocal inspections
        if path == child:
            inspections += 1
            return inspections > 1  # The second check happens just before descent.
        return original(path)

    monkeypatch.setattr(Path, "is_junction", replaced)
    assert scan(tmp_path).sources == ()
