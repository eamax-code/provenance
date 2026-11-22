"""Form 13F holdings and the internal CUSIP map (E-1).

Revision ID: b3e7d1f9a6c4
Revises: a9d3f1b7c5e2
"""

import sqlalchemy as sa
from alembic import op

from app.db.types import UTCDateTime

revision = "b3e7d1f9a6c4"
down_revision = "a9d3f1b7c5e2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "issuer_cusips",
        sa.Column("cusip", sa.String(9), primary_key=True),
        sa.Column("cik", sa.String(10), nullable=False),
        sa.Column("class_title", sa.Text(), nullable=True),
        sa.Column("method", sa.Text(), nullable=False),
        sa.Column("accession_number", sa.String(25), nullable=True),
        sa.Column("filing_date", sa.Date(), nullable=True),
        sa.Column("updated_at", UTCDateTime(), nullable=False),
    )
    op.create_index("ix_issuer_cusips_cik", "issuer_cusips", ["cik"])
    op.create_table(
        "filings_13f",
        sa.Column("accession_number", sa.String(25), primary_key=True),
        sa.Column("filer_cik", sa.String(10), nullable=False),
        sa.Column("filer_name", sa.Text(), nullable=False),
        sa.Column("report_period", sa.Date(), nullable=False),
        sa.Column("filing_date", sa.Date(), nullable=False),
        sa.Column("form_type", sa.Text(), nullable=False),
        sa.Column("amendment_type", sa.Text(), nullable=True),
        sa.Column("report_type", sa.Text(), nullable=True),
        sa.Column("entry_total", sa.Integer(), nullable=True),
        sa.Column("value_total_usd", sa.Numeric(24, 2), nullable=True),
        sa.Column("confidential_omitted", sa.Boolean(), nullable=False,
                  server_default=sa.false()),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("created_at", UTCDateTime(), nullable=False),
    )  # fmt: skip
    op.create_index("ix_filings_13f_filer_period", "filings_13f", ["filer_cik", "report_period"])
    op.create_index("ix_filings_13f_period", "filings_13f", ["report_period"])
    op.create_table(
        "holdings_13f",
        sa.Column("accession_number", sa.String(25), primary_key=True),
        sa.Column("cusip", sa.String(9), primary_key=True),
        sa.Column("filer_cik", sa.String(10), nullable=False),
        sa.Column("report_period", sa.Date(), nullable=False),
        sa.Column("filing_date", sa.Date(), nullable=False),
        sa.Column("title_of_class", sa.Text(), nullable=True),
        sa.Column("shares", sa.Numeric(24, 2), nullable=False),
        sa.Column("value_usd", sa.Numeric(24, 2), nullable=False),
    )
    op.create_index("ix_holdings_13f_cusip_period", "holdings_13f", ["cusip", "report_period"])


def downgrade() -> None:
    op.drop_table("holdings_13f")
    op.drop_table("filings_13f")
    op.drop_table("issuer_cusips")
