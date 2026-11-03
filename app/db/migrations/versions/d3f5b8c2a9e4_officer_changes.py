"""filing sections and officer changes from 8-K item 5.02

Revision ID: d3f5b8c2a9e4
Revises: c8e1a4d6f2b7
Create Date: 2026-11-03 17:00:00.000000

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from app.db.types import UTCDateTime

revision = "d3f5b8c2a9e4"
down_revision = "c8e1a4d6f2b7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "filing_sections",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("cik", sa.String(length=10), nullable=False),
        sa.Column("accession_number", sa.String(length=25), nullable=False),
        sa.Column("item", sa.String(length=10), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("text", sa.Text(), nullable=True),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("fetched_at", UTCDateTime(), nullable=False),
        sa.Column("extractor_version", sa.Text(), nullable=True),
        sa.Column("extraction_status", sa.Text(), nullable=True),
        sa.Column("extracted_at", UTCDateTime(), nullable=True),
        sa.Column("model", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("accession_number", "item", name="uq_filing_sections_accession_item"),
    )
    op.create_index("ix_filing_sections_cik", "filing_sections", ["cik"])
    op.create_table(
        "officer_changes",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("cik", sa.String(length=10), nullable=False),
        sa.Column("accession_number", sa.String(length=25), nullable=False),
        sa.Column("filing_date", sa.Date(), nullable=True),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("person", sa.Text(), nullable=True),
        sa.Column("role", sa.Text(), nullable=True),
        sa.Column("change_type", sa.Text(), nullable=False),
        sa.Column("what", sa.Text(), nullable=True),
        sa.Column("effective", sa.Text(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("successor", sa.Text(), nullable=True),
        sa.Column("evidence", sa.Text(), nullable=True),
        sa.Column("verified", sa.Boolean(), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("extractor_version", sa.Text(), nullable=False),
        sa.Column("model", sa.Text(), nullable=True),
        sa.Column("extracted_at", UTCDateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("accession_number", "seq", name="uq_officer_changes_accession_seq"),
    )
    op.create_index("ix_officer_changes_cik_filing_date", "officer_changes", ["cik", "filing_date"])


def downgrade() -> None:
    op.drop_index("ix_officer_changes_cik_filing_date", table_name="officer_changes")
    op.drop_table("officer_changes")
    op.drop_index("ix_filing_sections_cik", table_name="filing_sections")
    op.drop_table("filing_sections")
