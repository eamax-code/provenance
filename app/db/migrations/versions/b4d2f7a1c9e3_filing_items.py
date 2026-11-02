"""filing 8-K items

Revision ID: b4d2f7a1c9e3
Revises: a7c3e91f5b20
Create Date: 2026-11-03 14:00:00.000000

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "b4d2f7a1c9e3"
down_revision = "a7c3e91f5b20"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("filings", schema=None) as batch_op:
        batch_op.add_column(sa.Column("items", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("filings", schema=None) as batch_op:
        batch_op.drop_column("items")
