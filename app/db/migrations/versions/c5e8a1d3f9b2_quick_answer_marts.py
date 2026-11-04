"""Quick-answer marts: mart_company, mart_filing_activity and a form/date index (issue #8).

Revision ID: c5e8a1d3f9b2
Revises: b9d4e2f7a6c1
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from app.db.types import UTCDateTime

revision = "c5e8a1d3f9b2"
down_revision = "b9d4e2f7a6c1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "mart_company",
        sa.Column("cik", sa.String(10), primary_key=True),
        sa.Column("legal_name", sa.Text(), nullable=False),
        sa.Column("ticker", sa.Text()),
        sa.Column("exchange", sa.Text()),
        sa.Column("sic_code", sa.Text()),
        sa.Column("sic_description", sa.Text()),
        sa.Column("first_filing_date", sa.Date()),
        sa.Column("latest_filing_date", sa.Date()),
        sa.Column("filings_last_12_months", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("first_registration_date", sa.Date()),
        sa.Column("first_registration_form", sa.Text()),
        sa.Column("ipo_prospectus_date", sa.Date()),
        sa.Column("ipo_prospectus_accession", sa.String(25)),
        sa.Column("ipo_prospectus_url", sa.Text()),
        sa.Column("latest_annual_report_date", sa.Date()),
        sa.Column("latest_annual_report_form", sa.Text()),
        sa.Column("latest_revenue", sa.Numeric()),
        sa.Column("latest_revenue_period_end", sa.Date()),
        sa.Column("latest_annual", sa.Text()),
        sa.Column("revenue_history", sa.Text()),
        sa.Column("built_at", UTCDateTime(), nullable=False),
    )
    op.create_index("ix_mart_company_ipo_date", "mart_company", ["ipo_prospectus_date"])
    op.create_index("ix_mart_company_registration", "mart_company", ["first_registration_date"])
    op.create_index("ix_mart_company_latest_filing", "mart_company", ["latest_filing_date"])
    op.create_index("ix_mart_company_revenue", "mart_company", ["latest_revenue"])
    op.create_table(
        "mart_filing_activity",
        sa.Column("month", sa.Date(), primary_key=True),
        sa.Column("form_type", sa.Text(), primary_key=True),
        sa.Column("filings", sa.Integer(), nullable=False),
        sa.Column("companies", sa.Integer(), nullable=False),
    )
    # "Who filed a 10-K this week": filings by form and date across all companies.
    op.create_index("ix_filings_form_date", "filings", ["form_type", "filing_date"])


def downgrade() -> None:
    op.drop_index("ix_filings_form_date", table_name="filings")
    op.drop_table("mart_filing_activity")
    op.drop_index("ix_mart_company_revenue", table_name="mart_company")
    op.drop_index("ix_mart_company_latest_filing", table_name="mart_company")
    op.drop_index("ix_mart_company_registration", table_name="mart_company")
    op.drop_index("ix_mart_company_ipo_date", table_name="mart_company")
    op.drop_table("mart_company")
