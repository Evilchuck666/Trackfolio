"""Let users mark tracks as instrumental; a catalog-only flag never written to tags."""

from alembic import op

revision: str = "003_instrumental"
down_revision: str | None = "002_unique_artists"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE tracks ADD COLUMN instrumental BOOLEAN NOT NULL DEFAULT 0 "
        "CONSTRAINT ck_tracks_instrumental_boolean CHECK (instrumental IN (0, 1))"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE tracks DROP COLUMN instrumental")
