"""Segment labels from each filing's label linkbase (E-4b).

Revision ID: b7e3f9a1d5c2
Revises: a6d2e8f4c0b3
"""

import sqlalchemy as sa
from alembic import op

revision = "b7e3f9a1d5c2"
down_revision = "a6d2e8f4c0b3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "company_segments",
        sa.Column("label_source", sa.Text(), nullable=False, server_default="member_name"),
    )


def downgrade() -> None:
    op.drop_column("company_segments", "label_source")
