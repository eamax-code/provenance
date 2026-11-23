"""D-11 trading plans (Item 408(a)) and D-10 pay versus performance (Item 402(v)), both from
the ecd tags in the SEC's Financial Statement and Notes data sets; D-12 Form 144 notices.

Revision ID: e1a3c5e7f9b2
Revises: d8f0a2c4e6b1
"""

import sqlalchemy as sa
from alembic import op

revision = "e1a3c5e7f9b2"
down_revision = "d8f0a2c4e6b1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "trading_plans",
        sa.Column("id", sa.BigInteger().with_variant(sa.Integer(), "sqlite"), primary_key=True,
                  autoincrement=True),
        sa.Column("cik", sa.String(10), nullable=False),
        sa.Column("accession_number", sa.String(25), nullable=False),
        sa.Column("form_type", sa.Text(), nullable=False),
        sa.Column("filing_date", sa.Date(), nullable=False),
        sa.Column("period", sa.Date(), nullable=True),
        sa.Column("member", sa.Text(), nullable=False),
        sa.Column("person_name", sa.Text(), nullable=True),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("plan_type", sa.Text(), nullable=True),
        sa.Column("plan_date", sa.Date(), nullable=True),
        sa.Column("plan_date_text", sa.Text(), nullable=True),
        sa.Column("original_adoption_date", sa.Date(), nullable=True),
        sa.Column("duration_days", sa.Integer(), nullable=True),
        sa.Column("expiration_date", sa.Date(), nullable=True),
        sa.Column("shares", sa.Numeric(24, 4), nullable=True),
        sa.Column("source", sa.Text(), nullable=False),
        sa.UniqueConstraint("accession_number", "member", "action", name="uq_trading_plans_row"),
    )  # fmt: skip
    op.create_index("ix_trading_plans_cik_filed", "trading_plans", ["cik", "filing_date"])
    op.create_table(
        "proxy_pay_facts",
        sa.Column("id", sa.BigInteger().with_variant(sa.Integer(), "sqlite"), primary_key=True,
                  autoincrement=True),
        sa.Column("cik", sa.String(10), nullable=False),
        sa.Column("accession_number", sa.String(25), nullable=False),
        sa.Column("form_type", sa.Text(), nullable=False),
        sa.Column("filing_date", sa.Date(), nullable=False),
        sa.Column("fiscal_year_end", sa.Date(), nullable=True),
        sa.Column("field", sa.Text(), nullable=False),
        sa.Column("category", sa.Text(), nullable=True),
        sa.Column("member", sa.Text(), nullable=True),
        sa.Column("dims", sa.Text(), nullable=True),
        sa.Column("value_num", sa.Numeric(38, 6), nullable=True),
        sa.Column("value_text", sa.Text(), nullable=True),
        sa.Column("unit", sa.Text(), nullable=True),
        sa.Column("source", sa.Text(), nullable=False),
    )  # fmt: skip
    op.create_index("ix_proxy_pay_facts_cik_filed", "proxy_pay_facts", ["cik", "filing_date"])
    op.create_index("ix_proxy_pay_facts_accession", "proxy_pay_facts", ["accession_number"])
    op.create_table(
        "form144_notices",
        sa.Column("accession_number", sa.String(25), primary_key=True),
        sa.Column("issuer_cik", sa.String(10), nullable=False),
        sa.Column("form_type", sa.Text(), nullable=False),
        sa.Column("filing_date", sa.Date(), nullable=False),
        sa.Column("person_name", sa.Text(), nullable=True),
        sa.Column("person_cik", sa.String(10), nullable=True),
        sa.Column("relationships", sa.Text(), nullable=False),
        sa.Column("security_class", sa.Text(), nullable=True),
        sa.Column("shares", sa.Numeric(24, 4), nullable=True),
        sa.Column("aggregate_market_value", sa.Numeric(24, 2), nullable=True),
        sa.Column("shares_outstanding", sa.Numeric(24, 4), nullable=True),
        sa.Column("approx_sale_date", sa.Date(), nullable=True),
        sa.Column("exchange", sa.Text(), nullable=True),
        sa.Column("broker", sa.Text(), nullable=True),
        sa.Column("acquired", sa.Text(), nullable=False),
        sa.Column("acquired_count", sa.Integer(), nullable=False),
        sa.Column("plan_adoption_date", sa.Date(), nullable=True),
        sa.Column("notice_date", sa.Date(), nullable=True),
        sa.Column("source_url", sa.Text(), nullable=False),
    )
    op.create_index("ix_form144_notices_issuer_filed", "form144_notices",
                    ["issuer_cik", "filing_date"])  # fmt: skip


def downgrade() -> None:
    op.drop_table("form144_notices")
    op.drop_table("proxy_pay_facts")
    op.drop_table("trading_plans")
