"""event stream publication columns

Revision ID: a7c3e91f5b20
Revises: d761499d0f4d
Create Date: 2026-11-03 10:00:00.000000

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from app.db.types import UTCDateTime

revision = "a7c3e91f5b20"
down_revision = "d761499d0f4d"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Existing filings predate the feed and are treated as backfill (never streamed).
    with op.batch_alter_table("filings", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("stream_status", sa.Text(), server_default="skipped", nullable=False)
        )
        batch_op.add_column(sa.Column("stream_at", UTCDateTime(), nullable=True))
        batch_op.create_index("ix_filings_stream_status", ["stream_status"], unique=False)
        batch_op.create_index("ix_filings_stream_at", ["stream_at"], unique=False)
    # Existing listing events stay readable through the feed at their detection time.
    with op.batch_alter_table("listing_events", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("stream_status", sa.Text(), server_default="published", nullable=False)
        )
        batch_op.add_column(sa.Column("stream_at", UTCDateTime(), nullable=True))
        batch_op.create_index("ix_listing_events_stream_status", ["stream_status"], unique=False)
        batch_op.create_index("ix_listing_events_stream_at", ["stream_at"], unique=False)
    op.execute("UPDATE listing_events SET stream_at = detected_at WHERE stream_at IS NULL")


def downgrade() -> None:
    with op.batch_alter_table("listing_events", schema=None) as batch_op:
        batch_op.drop_index("ix_listing_events_stream_at")
        batch_op.drop_index("ix_listing_events_stream_status")
        batch_op.drop_column("stream_at")
        batch_op.drop_column("stream_status")
    with op.batch_alter_table("filings", schema=None) as batch_op:
        batch_op.drop_index("ix_filings_stream_at")
        batch_op.drop_index("ix_filings_stream_status")
        batch_op.drop_column("stream_at")
        batch_op.drop_column("stream_status")
