"""Create the initial metadata catalogue and its readable file view."""

from alembic import op
from sqlalchemy.schema import CreateIndex, CreateTable

from trackfolio.infrastructure.migrations.initial_schema import (
    APPLICATION_ID,
    TRACK_DETAILS_SQL,
    metadata,
)

revision: str = "001_initial"
down_revision: str | None = None
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    for table in metadata.sorted_tables:
        op.execute(CreateTable(table))
        # Table.indexes is a set; stable order makes the SQL export reproducible.
        for index in sorted(table.indexes, key=lambda item: str(item.name)):
            op.execute(CreateIndex(index))
    op.execute(TRACK_DETAILS_SQL)
    op.execute(f"PRAGMA application_id = {APPLICATION_ID}")


def downgrade() -> None:
    op.execute("DROP VIEW track_details")
    metadata.drop_all(bind=op.get_bind(), checkfirst=False)
