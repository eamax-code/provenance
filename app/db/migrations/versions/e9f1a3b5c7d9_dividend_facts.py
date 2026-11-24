"""Q-04: dividend_facts, dividends declared per share as every filing reports them (the same
columns as financial_facts; a known exception kept apart from the mapping).

Revision ID: e9f1a3b5c7d9
Revises: d8e0f2a4b6c7
"""

import sqlalchemy as sa
from alembic import op

from app.db.types import UTCDateTime

revision = "e9f1a3b5c7d9"
down_revision = "d8e0f2a4b6c7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "dividend_facts",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("cik", sa.String(10), nullable=False),
        sa.Column("metric", sa.Text(), nullable=False),
        sa.Column("value", sa.Numeric(38, 6), nullable=True),
        sa.Column("unit", sa.Text(), nullable=False),
        sa.Column("currency", sa.Text(), nullable=True),
        sa.Column("period_start", sa.Date(), nullable=True),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("period_type", sa.Text(), nullable=False),
        sa.Column("period_class", sa.Text(), nullable=False),
        sa.Column("fiscal_year", sa.Integer(), nullable=True),
        sa.Column("fiscal_period", sa.Text(), nullable=True),
        sa.Column("form_type", sa.Text(), nullable=True),
        sa.Column("filed_date", sa.Date(), nullable=True),
        sa.Column("accession_number", sa.String(25), nullable=True),
        sa.Column("source_tag", sa.Text(), nullable=False),
        sa.Column("source_taxonomy", sa.Text(), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("mapping_version", sa.Text(), nullable=False),
        sa.Column("quality_status", sa.Text(), nullable=False),
        sa.Column("derived", sa.Boolean(), nullable=False),
        sa.Column("derivation", sa.Text(), nullable=True),
        sa.Column("observation_key", sa.String(64), nullable=False),
        sa.Column("source_payload_hash", sa.Text(), nullable=True),
        sa.Column("first_detected_at", UTCDateTime(), nullable=False),
        sa.Column("processed_at", UTCDateTime(), nullable=False),
        sa.Column("created_at", UTCDateTime(), nullable=False),
        sa.UniqueConstraint("cik", "observation_key", name="uq_dividend_facts_cik_observation_key"),
    )
    op.create_index("ix_dividend_facts_cik_period_end", "dividend_facts", ["cik", "period_end"])


def downgrade() -> None:
    op.drop_index("ix_dividend_facts_cik_period_end", table_name="dividend_facts")
    op.drop_table("dividend_facts")
