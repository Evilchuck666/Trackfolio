"""Current Core schema, derived from the immutable initial migration snapshot."""

from sqlalchemy import Index, MetaData

from trackfolio.infrastructure.migrations import initial_schema
from trackfolio.infrastructure.migrations.initial_schema import APPLICATION_ID, TRACK_DETAILS_SQL

LEGACY_REVISION = initial_schema.REVISION
REVISION = "002_unique_artists"

# Copy each table before extending the schema, so revision 001 and its SQL export
# remain unchanged even when the current metadata is imported first.
metadata = MetaData(naming_convention=initial_schema.metadata.naming_convention)
for _table in initial_schema.metadata.sorted_tables:
    _table.to_metadata(metadata)

libraries = metadata.tables["libraries"]
albums = metadata.tables["albums"]
tracks = metadata.tables["tracks"]
artists = metadata.tables["artists"]
genres = metadata.tables["genres"]
track_artists = metadata.tables["track_artists"]
album_artists = metadata.tables["album_artists"]
track_genres = metadata.tables["track_genres"]
artworks = metadata.tables["artworks"]
audio_files = metadata.tables["audio_files"]
raw_tags = metadata.tables["raw_tags"]

Index("uq_artists_name", artists.c.name.collate("BINARY"), unique=True)

__all__ = [
    "APPLICATION_ID",
    "LEGACY_REVISION",
    "REVISION",
    "TRACK_DETAILS_SQL",
    "album_artists",
    "albums",
    "artists",
    "artworks",
    "audio_files",
    "genres",
    "libraries",
    "metadata",
    "raw_tags",
    "track_artists",
    "track_genres",
    "tracks",
]
