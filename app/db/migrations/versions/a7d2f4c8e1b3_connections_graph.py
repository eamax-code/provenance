"""Connections graph: insider filings and transactions, subsidiaries, 13D/G owners (GH #24).

Revision ID: a7d2f4c8e1b3
Revises: f3b8d2a7c4e9
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from app.db.types import BigSerial, UTCDateTime

revision = "a7d2f4c8e1b3"
down_revision = "f3b8d2a7c4e9"
branch_labels = None
depends_on = None


def _id() -> sa.Column:
    return sa.Column("id", BigSerial, primary_key=True, autoincrement=True)


def upgrade() -> None:
    op.create_table(
        "insider_filings",
        _id(),
        sa.Column("accession_number", sa.String(25), nullable=False),
        sa.Column("issuer_cik", sa.String(10), nullable=False),
        sa.Column("owner_cik", sa.String(10), nullable=False),
        sa.Column("owner_name", sa.Text(), nullable=False),
        sa.Column("is_director", sa.Boolean(), nullable=False),
        sa.Column("is_officer", sa.Boolean(), nullable=False),
        sa.Column("is_ten_percent_owner", sa.Boolean(), nullable=False),
        sa.Column("is_other", sa.Boolean(), nullable=False),
        sa.Column("officer_title", sa.Text(), nullable=True),
        sa.Column("other_text", sa.Text(), nullable=True),
        sa.Column("form_type", sa.Text(), nullable=False),
        sa.Column("filing_date", sa.Date(), nullable=False),
        sa.Column("period_of_report", sa.Date(), nullable=True),
        sa.Column("plan_10b5_1", sa.Boolean(), nullable=True),
        sa.Column("source", sa.Text(), nullable=False),
        sa.UniqueConstraint("accession_number", "owner_cik", name="uq_insider_filings_acc_owner"),
    )
    op.create_index(
        "ix_insider_filings_issuer_date", "insider_filings", ["issuer_cik", "filing_date"]
    )
    op.create_index(
        "ix_insider_filings_owner_date", "insider_filings", ["owner_cik", "filing_date"]
    )
    op.create_table(
        "insider_transactions",
        _id(),
        sa.Column("accession_number", sa.String(25), nullable=False),
        sa.Column("issuer_cik", sa.String(10), nullable=False),
        sa.Column("row_kind", sa.Text(), nullable=False),
        sa.Column("is_derivative", sa.Boolean(), nullable=False),
        sa.Column("row_key", sa.Text(), nullable=False),
        sa.Column("security_title", sa.Text(), nullable=True),
        sa.Column("trans_date", sa.Date(), nullable=True),
        sa.Column("trans_code", sa.String(4), nullable=True),
        sa.Column("shares", sa.Numeric(24, 4), nullable=True),
        sa.Column("price", sa.Numeric(24, 6), nullable=True),
        sa.Column("acquired_disposed", sa.String(1), nullable=True),
        sa.Column("shares_after", sa.Numeric(24, 4), nullable=True),
        sa.Column("direct_indirect", sa.String(1), nullable=True),
        sa.Column("nature_of_ownership", sa.Text(), nullable=True),
        sa.Column("underlying_title", sa.Text(), nullable=True),
        sa.Column("underlying_shares", sa.Numeric(24, 4), nullable=True),
        sa.Column("exercise_price", sa.Numeric(24, 6), nullable=True),
        sa.UniqueConstraint(
            "accession_number",
            "row_kind",
            "is_derivative",
            "row_key",
            name="uq_insider_transactions_row",
        ),  # fmt: skip
    )
    op.create_index(
        "ix_insider_transactions_issuer_date", "insider_transactions", ["issuer_cik", "trans_date"]
    )
    op.create_table(
        "insider_datasets",
        sa.Column("quarter", sa.String(6), primary_key=True),
        sa.Column("sha256", sa.Text(), nullable=False),
        sa.Column("filings", sa.Integer(), nullable=False),
        sa.Column("rows", sa.Integer(), nullable=False),
        sa.Column("last_filing_date", sa.Date(), nullable=True),
        sa.Column("loaded_at", UTCDateTime(), nullable=False),
    )
    op.create_table(
        "subsidiaries",
        _id(),
        sa.Column("cik", sa.String(10), nullable=False),
        sa.Column("accession_number", sa.String(25), nullable=False),
        sa.Column("form_type", sa.Text(), nullable=False),
        sa.Column("filing_date", sa.Date(), nullable=False),
        sa.Column("exhibit", sa.Text(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("jurisdiction", sa.Text(), nullable=True),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.UniqueConstraint("cik", "accession_number", "position", name="uq_subsidiaries_row"),
    )
    op.create_index("ix_subsidiaries_cik_date", "subsidiaries", ["cik", "filing_date"])
    op.create_table(
        "beneficial_owners",
        _id(),
        sa.Column("subject_cik", sa.String(10), nullable=False),
        sa.Column("accession_number", sa.String(25), nullable=False),
        sa.Column("form_type", sa.Text(), nullable=False),
        sa.Column("filing_date", sa.Date(), nullable=False),
        sa.Column("event_date", sa.Date(), nullable=True),
        sa.Column("filer_cik", sa.String(10), nullable=True),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("holder_name", sa.Text(), nullable=False),
        sa.Column("holder_cik", sa.String(10), nullable=True),
        sa.Column("holder_type", sa.Text(), nullable=True),
        sa.Column("shares", sa.Numeric(24, 4), nullable=True),
        sa.Column("percent", sa.Numeric(9, 4), nullable=True),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.UniqueConstraint(
            "subject_cik", "accession_number", "position", name="uq_beneficial_owners_row"
        ),
    )
    op.create_index(
        "ix_beneficial_owners_subject_date", "beneficial_owners", ["subject_cik", "filing_date"]
    )
    op.create_index("ix_beneficial_owners_filer", "beneficial_owners", ["filer_cik"])
    op.create_table(
        "graph_source_state",
        sa.Column("cik", sa.String(10), primary_key=True),
        sa.Column("kind", sa.Text(), primary_key=True),
        sa.Column("checked_at", UTCDateTime(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("detail", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("graph_source_state")
    op.drop_index("ix_beneficial_owners_filer", table_name="beneficial_owners")
    op.drop_index("ix_beneficial_owners_subject_date", table_name="beneficial_owners")
    op.drop_table("beneficial_owners")
    op.drop_index("ix_subsidiaries_cik_date", table_name="subsidiaries")
    op.drop_table("subsidiaries")
    op.drop_table("insider_datasets")
    op.drop_index("ix_insider_transactions_issuer_date", table_name="insider_transactions")
    op.drop_table("insider_transactions")
    op.drop_index("ix_insider_filings_owner_date", table_name="insider_filings")
    op.drop_index("ix_insider_filings_issuer_date", table_name="insider_filings")
    op.drop_table("insider_filings")
