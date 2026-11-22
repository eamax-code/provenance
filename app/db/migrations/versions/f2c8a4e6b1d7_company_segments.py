"""Segments by fiscal year from annual reports (E-4).

Revision ID: f2c8a4e6b1d7
Revises: e7b4f2a8c6d1
"""

import sqlalchemy as sa
from alembic import op

revision = "f2c8a4e6b1d7"
down_revision = "e7b4f2a8c6d1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "company_segments",
        sa.Column("accession_number", sa.String(25), primary_key=True),
        sa.Column("kind", sa.Text(), primary_key=True),
        sa.Column("member", sa.Text(), primary_key=True),
        sa.Column("metric", sa.Text(), primary_key=True),
        sa.Column("period_end", sa.Date(), primary_key=True),
        sa.Column("cik", sa.String(10), nullable=False),
        sa.Column("form_type", sa.Text(), nullable=False),
        sa.Column("fiscal_year", sa.Integer(), nullable=True),
        sa.Column("filed_date", sa.Date(), nullable=False),
        sa.Column("label", sa.Text(), nullable=False),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column("tag", sa.Text(), nullable=False),
        sa.Column("unit", sa.Text(), nullable=False),
        sa.Column("value", sa.Numeric(24, 2), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
    )
    op.create_index("ix_company_segments_cik_filed", "company_segments", ["cik", "filed_date"])


def downgrade() -> None:
    op.drop_table("company_segments")
