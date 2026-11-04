"""Group album editions by credited artists without changing catalogue data."""

from trackfolio.domain.album import Album


def group_artists(albums: tuple[Album, ...]) -> dict[str | None, tuple[Album, ...]]:
    groups: dict[str | None, list[Album]] = {}
    for album in albums:
        names = album.artists
        if not names and album.tracks:
            credits = {track.summary.artists for track in album.tracks}
            if len(credits) == 1:
                names = next(iter(credits))
        for name in dict.fromkeys(names or (None,)):
            groups.setdefault(name, []).append(album)
    return {
        name: tuple(
            sorted(
                editions,
                key=lambda a: (a.year is None, a.year or 0, (a.title or "").casefold(), a.key),
            )
        )
        for name, editions in sorted(
            groups.items(),
            key=lambda pair: (pair[0] is None, (pair[0] or "").casefold(), pair[0] or ""),
        )
    }
