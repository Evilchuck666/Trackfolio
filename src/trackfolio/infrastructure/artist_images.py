"""Read optional artist portraits from the parent folders of album editions."""

from trackfolio.domain.album import Album


def read_artist_image(albums: tuple[Album, ...]) -> bytes | None:
    folders = sorted({(album.library_root / album.directory).parent for album in albums})
    for folder in folders:
        try:
            candidates = sorted(
                (path for path in folder.iterdir() if path.suffix.casefold() in (".jpg", ".jpeg")),
                key=lambda path: (
                    {"artist": 0, "folder": 1}.get(path.stem.casefold(), 2),
                    path.name.casefold(),
                    path.name,
                ),
            )
        except OSError:
            continue
        for path in candidates:
            try:
                if path.is_symlink() or not path.is_file():
                    continue
                with path.open("rb") as stream:
                    data = stream.read(16 * 1024 * 1024 + 1)
                if len(data) <= 16 * 1024 * 1024 and data.startswith(b"\xff\xd8\xff"):
                    return data
            except OSError:
                continue
    return None
