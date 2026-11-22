"""Audit firms from annual-report cover tags (E-3).

Revision ID: d1a7c3e9f5b2
Revises: c8f2a6d4e1b9
"""

import sqlalchemy as sa
from alembic import op

revision = "d1a7c3e9f5b2"
down_revision = "c8f2a6d4e1b9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "company_auditors",
        sa.Column("accession_number", sa.String(25), primary_key=True),
        sa.Column("auditor_key", sa.Text(), primary_key=True),
        sa.Column("cik", sa.String(10), nullable=False),
        sa.Column("form_type", sa.Text(), nullable=False),
        sa.Column("fiscal_year", sa.Integer(), nullable=True),
        sa.Column("period_end", sa.Date(), nullable=True),
        sa.Column("audited_through", sa.Date(), nullable=True),
        sa.Column("filed_date", sa.Date(), nullable=False),
        sa.Column("auditor_name", sa.Text(), nullable=False),
        sa.Column("pcaob_firm_id", sa.Text(), nullable=True),
        sa.Column("auditor_location", sa.Text(), nullable=True),
        sa.Column("source", sa.Text(), nullable=False),
    )
    op.create_index("ix_company_auditors_cik_filed", "company_auditors", ["cik", "filed_date"])


def downgrade() -> None:
    op.drop_table("company_auditors")
