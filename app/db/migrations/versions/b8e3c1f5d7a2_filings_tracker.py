"""Filings tracker: every filing EDGAR lists, read hourly, and job progress markers (ADR 0012).

Revision ID: b8e3c1f5d7a2
Revises: a7d2f4c8e1b3
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from app.db.types import BigSerial, UTCDateTime

revision = "b8e3c1f5d7a2"
down_revision = "a7d2f4c8e1b3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "edgar_feed",
        sa.Column("id", BigSerial, primary_key=True, autoincrement=True),
        sa.Column("accession_number", sa.String(25), nullable=False),
        sa.Column("cik", sa.String(10), nullable=False),
        sa.Column("company_name", sa.Text(), nullable=False),
        sa.Column("form_type", sa.Text(), nullable=False),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column("filing_date", sa.Date()),
        sa.Column("accepted_at", UTCDateTime()),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("seen_at", UTCDateTime(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("handled_at", UTCDateTime()),
        sa.Column("detail", sa.Text()),
        sa.UniqueConstraint("accession_number", "cik", name="uq_edgar_feed_accession_cik"),
    )
    op.create_index("ix_edgar_feed_status", "edgar_feed", ["status"])
    op.create_index("ix_edgar_feed_cik", "edgar_feed", ["cik"])
    op.create_index("ix_edgar_feed_form_date", "edgar_feed", ["form_type", "filing_date"])
    op.create_table(
        "job_state",
        sa.Column("name", sa.Text(), primary_key=True),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("updated_at", UTCDateTime(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("job_state")
    op.drop_index("ix_edgar_feed_form_date", table_name="edgar_feed")
    op.drop_index("ix_edgar_feed_cik", table_name="edgar_feed")
    op.drop_index("ix_edgar_feed_status", table_name="edgar_feed")
    op.drop_table("edgar_feed")
