"""Watches can be paused without being stopped (A-01).

Revision ID: a9d3f1b7c5e2
Revises: f8a2c4e6b0d3
"""

import sqlalchemy as sa
from alembic import op

revision = "a9d3f1b7c5e2"
down_revision = "f8a2c4e6b0d3"
branch_labels = None
depends_on = None
TABLES = ("company_watches", "listing_watches", "type_watches")


def upgrade() -> None:
    for t in TABLES:
        op.add_column(t, sa.Column("paused", sa.Boolean(), nullable=False,
                                   server_default=sa.false()))  # fmt: skip


def downgrade() -> None:
    for t in TABLES:
        op.drop_column(t, "paused")
