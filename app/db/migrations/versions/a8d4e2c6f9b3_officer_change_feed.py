"""officer_changes on the event feed (stream_status, stream_at) with context (ticket 20).

Existing rows become published without a stream time, so they never appear as new events.

Revision ID: a8d4e2c6f9b3
Revises: f7c3d9e1b2a4
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from app.db.types import UTCDateTime

revision = "a8d4e2c6f9b3"
down_revision = "f7c3d9e1b2a4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "officer_changes",
        sa.Column("stream_status", sa.Text(), nullable=False, server_default="published"),
    )
    op.add_column("officer_changes", sa.Column("stream_at", UTCDateTime(), nullable=True))
    op.add_column("officer_changes", sa.Column("context", sa.Text(), nullable=True))
    op.create_index("ix_officer_changes_stream_at", "officer_changes", ["stream_at"])


def downgrade() -> None:
    op.drop_index("ix_officer_changes_stream_at", table_name="officer_changes")
    with op.batch_alter_table("officer_changes") as batch:
        batch.drop_column("context")
        batch.drop_column("stream_at")
        batch.drop_column("stream_status")
