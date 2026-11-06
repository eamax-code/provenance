"""rate_limit_counters: fixed-window counts shared by every API replica (ticket 12).

Revision ID: d3a9f7c2e5b1
Revises: c8e4a2f6d1b9
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "d3a9f7c2e5b1"
down_revision = "c8e4a2f6d1b9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "rate_limit_counters",
        sa.Column("key", sa.Text(), primary_key=True),
        sa.Column("window_start", sa.BigInteger(), primary_key=True),
        sa.Column("count", sa.Integer(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("rate_limit_counters")
