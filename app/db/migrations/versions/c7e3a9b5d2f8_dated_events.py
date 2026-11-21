"""Events on a date rather than in a filing, such as an IPO lock-up ending (F-02).

Revision ID: c7e3a9b5d2f8
Revises: b2d8f6a4c1e9
"""

import sqlalchemy as sa
from alembic import op

from app.db.types import UTCDateTime

revision = "c7e3a9b5d2f8"
down_revision = "b2d8f6a4c1e9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "dated_events",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("cik", sa.String(10), nullable=False),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("event_date", sa.Date(), nullable=False),
        sa.Column("accession_number", sa.String(25), nullable=False),
        sa.Column("detail", sa.Text(), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("stream_status", sa.Text(), nullable=False),
        sa.Column("stream_at", UTCDateTime()),
        sa.Column("created_at", UTCDateTime(), nullable=False),
        sa.UniqueConstraint("event_type", "cik", "accession_number", name="uq_dated_events"),
    )
    op.create_index("ix_dated_events_date", "dated_events", ["event_date"])
    with op.batch_alter_table("notification_deliveries") as batch:
        batch.add_column(sa.Column("dated_event_id", sa.Uuid(), nullable=True))
        batch.create_foreign_key(
            "fk_deliveries_dated_event", "dated_events", ["dated_event_id"], ["id"]
        )


def downgrade() -> None:
    with op.batch_alter_table("notification_deliveries") as batch:
        batch.drop_constraint("fk_deliveries_dated_event", type_="foreignkey")
        batch.drop_column("dated_event_id")
    op.drop_index("ix_dated_events_date", table_name="dated_events")
    op.drop_table("dated_events")
