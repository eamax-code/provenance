"""SEC filers linked to their LEI, with match method and confidence; manual overrides (K-01).

Revision ID: b2d8f6a4c1e9
Revises: a1c9e5f3b7d4
"""

import sqlalchemy as sa
from alembic import op

from app.db.types import UTCDateTime

revision = "b2d8f6a4c1e9"
down_revision = "a1c9e5f3b7d4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "company_lei",
        sa.Column("cik", sa.String(10), primary_key=True),
        sa.Column("lei", sa.String(20), nullable=False),
        sa.Column("match_method", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Text(), nullable=False),
        sa.Column("evidence", sa.Text(), nullable=False),
        sa.Column("matched_at", UTCDateTime(), nullable=False),
    )
    op.create_index("ix_company_lei_lei", "company_lei", ["lei"])
    op.create_table(
        "lei_overrides",
        sa.Column("cik", sa.String(10), primary_key=True),
        sa.Column("lei", sa.String(20)),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column("created_at", UTCDateTime(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("lei_overrides")
    op.drop_index("ix_company_lei_lei", table_name="company_lei")
    op.drop_table("company_lei")
