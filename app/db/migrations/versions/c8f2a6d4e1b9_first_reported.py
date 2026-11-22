"""Figures first stated in 8-K 2.02 earnings releases (E-2).

Revision ID: c8f2a6d4e1b9
Revises: b3e7d1f9a6c4
"""

import sqlalchemy as sa
from alembic import op

from app.db.types import UTCDateTime

revision = "c8f2a6d4e1b9"
down_revision = "b3e7d1f9a6c4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "first_reported",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("cik", sa.String(10), nullable=False),
        sa.Column("metric", sa.Text(), nullable=False),
        sa.Column("unit", sa.Text(), nullable=False),
        sa.Column("period_start", sa.Date(), nullable=True),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("value", sa.Numeric(38, 6), nullable=False),
        sa.Column("fact_accession", sa.String(25), nullable=False),
        sa.Column("release_accession", sa.String(25), nullable=False),
        sa.Column("release_filing_date", sa.Date(), nullable=False),
        sa.Column("release_url", sa.Text(), nullable=False),
        sa.Column("stated_as", sa.Text(), nullable=False),
        sa.Column("evidence", sa.Text(), nullable=False),
        sa.Column("created_at", UTCDateTime(), nullable=False),
        sa.UniqueConstraint("cik", "metric", "unit", "period_start", "period_end",
                            "fact_accession", name="uq_first_reported_fact"),
    )  # fmt: skip
    op.create_index("ix_first_reported_fact", "first_reported", ["fact_accession", "metric"])


def downgrade() -> None:
    op.drop_table("first_reported")
