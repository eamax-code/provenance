"""mart_financials and mart_company_period (issue #3, ADR 0009).

Revision ID: e9a3c6f1b4d8
Revises: d7f2b4c8e1a6
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "e9a3c6f1b4d8"
down_revision = "d7f2b4c8e1a6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "mart_financials",
        sa.Column("cik", sa.String(10), primary_key=True),
        sa.Column("metric", sa.Text(), primary_key=True),
        sa.Column("period_class", sa.Text(), primary_key=True),
        sa.Column("unit", sa.Text(), primary_key=True),
        sa.Column("period_end", sa.Date(), primary_key=True),
        sa.Column("period_start", sa.Date()),
        sa.Column("value", sa.Numeric(), nullable=False),
        sa.Column("currency", sa.Text()),
        sa.Column("fiscal_year", sa.Integer(), nullable=False),
        sa.Column("fiscal_quarter", sa.Integer()),
        sa.Column("form_type", sa.Text()),
        sa.Column("filed_date", sa.Date()),
        sa.Column("accession_number", sa.String(25)),
        sa.Column("source_tag", sa.Text(), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("quality_status", sa.Text(), nullable=False),
        sa.Column("mapping_version", sa.Text(), nullable=False),
    )
    op.create_index(
        "ix_mart_financials_screen",
        "mart_financials",
        ["metric", "period_class", "unit", "period_end", "cik"],
    )
    op.create_index(
        "ix_mart_financials_company",
        "mart_financials",
        ["cik", "metric", "period_class", "period_end"],
    )
    op.create_table(
        "mart_company_period",
        sa.Column("cik", sa.String(10), primary_key=True),
        sa.Column("fiscal_year", sa.Integer(), primary_key=True),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("revenue", sa.Numeric()),
        sa.Column("operating_income", sa.Numeric()),
        sa.Column("net_income", sa.Numeric()),
        sa.Column("total_assets", sa.Numeric()),
        sa.Column("operating_cash_flow", sa.Numeric()),
        sa.Column("sources", sa.Text()),
    )


def downgrade() -> None:
    op.drop_table("mart_company_period")
    op.drop_index("ix_mart_financials_company", table_name="mart_financials")
    op.drop_index("ix_mart_financials_screen", table_name="mart_financials")
    op.drop_table("mart_financials")
