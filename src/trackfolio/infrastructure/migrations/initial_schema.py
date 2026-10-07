"""Schema snapshot for revision 001_initial; do not alter an applied revision.

The initial migration, SQL export and current Core tables share this definition.
Future schema changes must introduce a new migration rather than edit this snapshot.
"""

from sqlalchemy import (
    CheckConstraint,
    Column,
    Float,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    MetaData,
    String,
    Table,
    Text,
    UniqueConstraint,
)

REVISION = "001_initial"
APPLICATION_ID = 0x54464F4C
metadata = MetaData(
    naming_convention={
        "ix": "ix_%(table_name)s_%(column_0_name)s",
        "uq": "uq_%(table_name)s_%(column_0_name)s",
        "ck": "ck_%(table_name)s_%(constraint_name)s",
        "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
        "pk": "pk_%(table_name)s",
    }
)

libraries = Table(
    "libraries",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("root_path", Text, nullable=False, unique=True),
    CheckConstraint("length(root_path) > 0", name="root_path_nonempty"),
)

albums = Table(
    "albums",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("library_id", ForeignKey("libraries.id", ondelete="CASCADE"), nullable=False),
    Column("directory", Text, nullable=False),
    Column("import_key", String(64), nullable=False),
    Column("title", Text),
    Column("year", Integer),
    Column("date", Text),
    Column("disc_total", Integer),
    UniqueConstraint("library_id", "import_key"),
    CheckConstraint("length(directory) > 0", name="directory_nonempty"),
    CheckConstraint("length(import_key) > 0", name="import_key_nonempty"),
    CheckConstraint(
        "year IS NULL OR (typeof(year) = 'integer' AND year > 0)", name="year_positive"
    ),
    CheckConstraint(
        "disc_total IS NULL OR (typeof(disc_total) = 'integer' AND disc_total > 0)",
        name="disc_total_positive",
    ),
)
Index("ix_albums_library_directory", albums.c.library_id, albums.c.directory)

tracks = Table(
    "tracks",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("album_id", ForeignKey("albums.id", ondelete="SET NULL"), index=True),
    Column("title", Text),
    Column("track_number", Integer),
    Column("track_total", Integer),
    Column("disc_number", Integer),
    Column("disc_total", Integer),
    Column("lyrics", Text),
    *(
        CheckConstraint(
            f"{field} IS NULL OR (typeof({field}) = 'integer' AND {field} > 0)",
            name=f"{field}_positive",
        )
        for field in ("track_number", "track_total", "disc_number", "disc_total")
    ),
)

artists = Table(
    "artists",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("name", Text, nullable=False),
    Column("external_id", Text, index=True),
    CheckConstraint("length(name) > 0", name="name_nonempty"),
)

genres = Table(
    "genres",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("name", Text, nullable=False, unique=True),
    CheckConstraint("length(name) > 0", name="name_nonempty"),
)

track_artists = Table(
    "track_artists",
    metadata,
    Column("track_id", ForeignKey("tracks.id", ondelete="CASCADE"), primary_key=True),
    Column("role", Text, primary_key=True, server_default="artist"),
    Column("position", Integer, primary_key=True),
    Column("artist_id", ForeignKey("artists.id", ondelete="RESTRICT"), nullable=False, index=True),
    CheckConstraint("typeof(position) = 'integer' AND position >= 0", name="position_nonnegative"),
    CheckConstraint("length(role) > 0", name="role_nonempty"),
)

album_artists = Table(
    "album_artists",
    metadata,
    Column("album_id", ForeignKey("albums.id", ondelete="CASCADE"), primary_key=True),
    Column("role", Text, primary_key=True, server_default="album_artist"),
    Column("position", Integer, primary_key=True),
    Column("artist_id", ForeignKey("artists.id", ondelete="RESTRICT"), nullable=False, index=True),
    CheckConstraint("typeof(position) = 'integer' AND position >= 0", name="position_nonnegative"),
    CheckConstraint("length(role) > 0", name="role_nonempty"),
)

track_genres = Table(
    "track_genres",
    metadata,
    Column("track_id", ForeignKey("tracks.id", ondelete="CASCADE"), primary_key=True),
    Column("position", Integer, primary_key=True),
    Column("genre_id", ForeignKey("genres.id", ondelete="RESTRICT"), nullable=False, index=True),
    CheckConstraint("typeof(position) = 'integer' AND position >= 0", name="position_nonnegative"),
)

artworks = Table(
    "artworks",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("sha256", String(64), nullable=False, unique=True),
    Column("data", LargeBinary, nullable=False),
    Column("mime", Text, nullable=False),
    Column("width", Integer),
    Column("height", Integer),
    CheckConstraint("length(sha256) = 64 AND sha256 NOT GLOB '*[^0-9a-f]*'", name="sha256_digest"),
    CheckConstraint("length(data) > 0", name="data_nonempty"),
    CheckConstraint("length(mime) > 0", name="mime_nonempty"),
    CheckConstraint(
        "width IS NULL OR (typeof(width) = 'integer' AND width > 0)", name="width_positive"
    ),
    CheckConstraint(
        "height IS NULL OR (typeof(height) = 'integer' AND height > 0)", name="height_positive"
    ),
)

audio_files = Table(
    "audio_files",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("library_id", ForeignKey("libraries.id", ondelete="CASCADE"), nullable=False),
    Column("relative_path", Text, nullable=False),
    Column("track_id", ForeignKey("tracks.id", ondelete="CASCADE"), nullable=False, index=True),
    Column("format", Text, nullable=False),
    Column("duration_seconds", Float),
    Column("sample_rate_hz", Integer),
    Column("channels", Integer),
    Column("bits_per_sample", Integer),
    Column("cover_artwork_id", ForeignKey("artworks.id", ondelete="RESTRICT"), index=True),
    Column("cover_source", Text),
    Column("cover_relative_path", Text),
    UniqueConstraint("library_id", "relative_path"),
    CheckConstraint("format IN ('FLAC', 'MP3')", name="supported_format"),
    CheckConstraint("length(relative_path) > 0", name="relative_path_nonempty"),
    CheckConstraint(
        "duration_seconds IS NULL OR (typeof(duration_seconds) IN ('integer', 'real') "
        "AND duration_seconds >= 0)",
        name="duration_nonnegative",
    ),
    *(
        CheckConstraint(
            f"{field} IS NULL OR (typeof({field}) = 'integer' AND {field} > 0)",
            name=f"{field}_positive",
        )
        for field in ("sample_rate_hz", "channels", "bits_per_sample")
    ),
    CheckConstraint(
        "(cover_artwork_id IS NULL AND cover_source IS NULL AND cover_relative_path IS NULL) "
        "OR (cover_artwork_id IS NOT NULL AND cover_source IS NOT NULL "
        "AND cover_source = 'embedded' "
        "AND cover_relative_path IS NULL) "
        "OR (cover_artwork_id IS NOT NULL AND cover_source IS NOT NULL "
        "AND cover_source = 'album.jpg' "
        "AND cover_relative_path IS NOT NULL AND length(cover_relative_path) > 0)",
        name="cover_consistent",
    ),
)

raw_tags = Table(
    "raw_tags",
    metadata,
    Column("file_id", ForeignKey("audio_files.id", ondelete="CASCADE"), primary_key=True),
    Column("key", Text, primary_key=True),
    Column("position", Integer, primary_key=True),
    Column("value", Text, nullable=False),
    CheckConstraint("typeof(position) = 'integer' AND position >= 0", name="position_nonnegative"),
)

TRACK_DETAILS_SQL = """CREATE VIEW track_details AS
SELECT
    f.id AS file_id,
    t.id AS track_id,
    f.library_id,
    f.relative_path,
    f.format,
    t.title,
    a.title AS album,
    a.year AS album_year,
    a.date AS album_date,
    t.track_number,
    t.track_total,
    t.disc_number,
    t.disc_total,
    (SELECT group_concat(name, '; ') FROM (
        SELECT artist.name AS name
        FROM track_artists AS credit JOIN artists AS artist ON artist.id = credit.artist_id
        WHERE credit.track_id = t.id
        ORDER BY credit.position, credit.role
    )) AS artists,
    (SELECT group_concat(name, '; ') FROM (
        SELECT artist.name AS name
        FROM album_artists AS credit JOIN artists AS artist ON artist.id = credit.artist_id
        WHERE credit.album_id = a.id
        ORDER BY credit.position, credit.role
    )) AS album_artists,
    (SELECT group_concat(name, '; ') FROM (
        SELECT genre.name AS name
        FROM track_genres AS credit JOIN genres AS genre ON genre.id = credit.genre_id
        WHERE credit.track_id = t.id
        ORDER BY credit.position
    )) AS genres,
    t.lyrics,
    f.duration_seconds,
    f.sample_rate_hz,
    f.channels,
    f.bits_per_sample,
    f.cover_source,
    f.cover_relative_path,
    artwork.mime AS cover_mime,
    length(artwork.data) AS cover_bytes,
    artwork.width AS cover_width,
    artwork.height AS cover_height
FROM audio_files AS f
JOIN tracks AS t ON t.id = f.track_id
LEFT JOIN albums AS a ON a.id = t.album_id
LEFT JOIN artworks AS artwork ON artwork.id = f.cover_artwork_id"""
