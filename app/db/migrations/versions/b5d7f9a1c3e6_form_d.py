"""D-15 Form D filings from the SEC's structured Form D data sets.

Revision ID: b5d7f9a1c3e6
Revises: a4c6e8f0b2d5
"""

import sqlalchemy as sa
from alembic import op

revision = "b5d7f9a1c3e6"
down_revision = "a4c6e8f0b2d5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "form_d_filings",
        sa.Column("accession_number", sa.String(25), primary_key=True),
        sa.Column("file_number", sa.Text(), nullable=True),
        sa.Column("form_type", sa.Text(), nullable=False),
        sa.Column("filing_date", sa.Date(), nullable=False),
        sa.Column("cik", sa.String(10), nullable=False),
        sa.Column("issuer_name", sa.Text(), nullable=False),
        sa.Column("state", sa.Text(), nullable=True),
        sa.Column("jurisdiction", sa.Text(), nullable=True),
        sa.Column("entity_type", sa.Text(), nullable=True),
        sa.Column("year_of_incorporation", sa.Text(), nullable=True),
        sa.Column("industry_group", sa.Text(), nullable=True),
        sa.Column("total_offering_amount", sa.Numeric(24, 2), nullable=True),
        sa.Column("indefinite", sa.Boolean(), nullable=False),
        sa.Column("total_amount_sold", sa.Numeric(24, 2), nullable=True),
        sa.Column("total_remaining", sa.Numeric(24, 2), nullable=True),
        sa.Column("investors_total", sa.Integer(), nullable=True),
        sa.Column("investors_non_accredited", sa.Integer(), nullable=True),
        sa.Column("first_sale_date", sa.Date(), nullable=True),
        sa.Column("first_sale_yet_to_occur", sa.Boolean(), nullable=False),
        sa.Column("exemptions", sa.Text(), nullable=True),
        sa.Column("minimum_investment", sa.Numeric(24, 2), nullable=True),
        sa.Column("sales_commissions", sa.Numeric(24, 2), nullable=True),
        sa.Column("finders_fees", sa.Numeric(24, 2), nullable=True),
        sa.Column("related_persons", sa.Text(), nullable=False),
        sa.Column("related_persons_count", sa.Integer(), nullable=False),
        sa.Column("is_latest", sa.Boolean(), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
    )
    op.create_index("ix_form_d_filings_cik", "form_d_filings", ["cik"])
    op.create_index("ix_form_d_filings_file", "form_d_filings", ["file_number"])
    op.create_index("ix_form_d_filings_latest", "form_d_filings", ["is_latest", "filing_date"])


def downgrade() -> None:
    op.drop_table("form_d_filings")
