"""Share each exact artist name across the catalogue, preserving all credits."""

from alembic import op

revision: str = "002_unique_artists"
down_revision: str | None = "001_initial"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    # Legacy catalogues have no name index. Keep exact-name lookups efficient
    # while consolidating potentially large artist and credit tables.
    op.execute("CREATE INDEX ix_artists_name_consolidation ON artists (name COLLATE BINARY)")
    # Keep a canonical external ID when present; otherwise take the first
    # non-null value by original ID. This also works in exported offline SQL.
    op.execute(
        """UPDATE artists AS canonical
SET external_id = (
    SELECT original.external_id
    FROM artists AS original
    WHERE original.name = canonical.name COLLATE BINARY
      AND original.external_id IS NOT NULL
    ORDER BY original.id
    LIMIT 1
)
WHERE canonical.external_id IS NULL
  AND canonical.id IN (SELECT MIN(id) FROM artists GROUP BY name COLLATE BINARY)"""
    )
    for credits in ("track_artists", "album_artists"):
        op.execute(
            f"""UPDATE {credits}
SET artist_id = (
    SELECT MIN(canonical.id)
    FROM artists AS canonical
    JOIN artists AS original ON canonical.name = original.name COLLATE BINARY
    WHERE original.id = {credits}.artist_id
)
WHERE artist_id NOT IN (SELECT MIN(id) FROM artists GROUP BY name COLLATE BINARY)"""
        )
    op.execute(
        "DELETE FROM artists "
        "WHERE id NOT IN (SELECT MIN(id) FROM artists GROUP BY name COLLATE BINARY)"
    )
    op.drop_index("ix_artists_name_consolidation", table_name="artists")
    op.execute("CREATE UNIQUE INDEX uq_artists_name ON artists (name COLLATE BINARY)")


def downgrade() -> None:
    # Consolidated identities cannot recover the former duplicates. A backup
    # restores those; downgrade only removes the new uniqueness guarantee.
    op.drop_index("uq_artists_name", table_name="artists")
