"""Insider activity found by rules in Forms 4, on the feed and type watches (F-03).

Revision ID: a1c9e5f3b7d4
Revises: f6b1d8e4a2c7
"""

import sqlalchemy as sa
from alembic import op

from app.db.types import UTCDateTime

revision = "a1c9e5f3b7d4"
down_revision = "f6b1d8e4a2c7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "insider_activity",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("cik", sa.String(10), nullable=False),
        sa.Column("activity_type", sa.Text(), nullable=False),
        sa.Column("activity_date", sa.Date(), nullable=False),
        sa.Column("filing_date", sa.Date(), nullable=False),
        sa.Column("accession_number", sa.String(25), nullable=False),
        sa.Column("owners", sa.Text(), nullable=False),
        sa.Column("detail", sa.Text(), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("stream_status", sa.Text(), nullable=False),
        sa.Column("stream_at", UTCDateTime()),
        sa.Column("created_at", UTCDateTime(), nullable=False),
        sa.UniqueConstraint("activity_type", "cik", "accession_number", name="uq_insider_activity"),
    )
    op.create_index("ix_insider_activity_cik_date", "insider_activity", ["cik", "activity_date"])
    op.create_index(
        "ix_insider_activity_stream", "insider_activity", ["stream_status", "stream_at"]
    )
    with op.batch_alter_table("notification_deliveries") as batch:
        batch.add_column(sa.Column("insider_activity_id", sa.Uuid(), nullable=True))
        batch.create_foreign_key(
            "fk_deliveries_insider_activity", "insider_activity", ["insider_activity_id"], ["id"]
        )


def downgrade() -> None:
    with op.batch_alter_table("notification_deliveries") as batch:
        batch.drop_constraint("fk_deliveries_insider_activity", type_="foreignkey")
        batch.drop_column("insider_activity_id")
    op.drop_index("ix_insider_activity_stream", table_name="insider_activity")
    op.drop_index("ix_insider_activity_cik_date", table_name="insider_activity")
    op.drop_table("insider_activity")
