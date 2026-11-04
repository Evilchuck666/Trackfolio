"""Artist pictures are read only from album parents with deterministic priority."""

from trackfolio.domain.album import Album
from trackfolio.infrastructure.artist_images import read_artist_image


def test_portrait_priority_and_case_insensitive_extensions(tmp_path):
    folder = tmp_path / "Artist"
    folder.mkdir()
    album = Album("one", "Album", 2000, ("Artist",), tmp_path, "Artist/Album", ())
    for name in ("z.JPG", "folder.jpg", "artist.JPEG"):
        (folder / name).write_bytes(b"\xff\xd8\xff" + name.encode())
    assert read_artist_image((album,)) == b"\xff\xd8\xffartist.JPEG"
    (folder / "artist.JPEG").unlink()
    assert read_artist_image((album,)) == b"\xff\xd8\xfffolder.jpg"


def test_missing_invalid_and_album_images_are_ignored(tmp_path):
    folder = tmp_path / "Artist"
    album_folder = folder / "Album"
    album_folder.mkdir(parents=True)
    album = Album("one", "Album", 2000, ("Artist",), tmp_path, "Artist/Album", ())
    (album_folder / "folder.jpg").write_bytes(b"\xff\xd8\xffcover")
    (folder / "bad.jpg").write_bytes(b"not an image")
    (folder / "directory.jpg").mkdir()
    assert read_artist_image((album,)) is None
    assert read_artist_image(()) is None
