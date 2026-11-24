"""Q-02: per-security quarter stats, the per-filing thousands check and the funds activity list.

Revision ID: f4a6b8c0d2e3
Revises: e3f5a7b9c1d2
"""

import sqlalchemy as sa
from alembic import op

revision = "f4a6b8c0d2e3"
down_revision = "e3f5a7b9c1d2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "thirteenf_security_stats",
        sa.Column("cusip", sa.String(9), primary_key=True),
        sa.Column("report_period", sa.Date(), primary_key=True),
        sa.Column("holders", sa.Integer(), nullable=False),
        sa.Column("shares", sa.Float(), nullable=False),
        sa.Column("value_usd", sa.Float(), nullable=False),
        sa.Column("median_price", sa.Float(), nullable=True),
    )
    op.create_table(
        "thirteenf_filing_scale",
        sa.Column("accession_number", sa.String(25), primary_key=True),
        sa.Column("report_period", sa.Date(), nullable=False),
        sa.Column("price_ratio", sa.Float(), nullable=True),
        sa.Column("suspect", sa.Boolean(), nullable=False),
    )
    op.create_table(
        "thirteenf_activity",
        sa.Column("report_period", sa.Date(), primary_key=True),
        sa.Column("issuer_cik", sa.String(10), primary_key=True),
        sa.Column("class_label", sa.Text(), primary_key=True),
        sa.Column("previous_period", sa.Date(), nullable=False),
        sa.Column("managers_new", sa.Integer(), nullable=False),
        sa.Column("managers_added", sa.Integer(), nullable=False),
        sa.Column("managers_reduced", sa.Integer(), nullable=False),
        sa.Column("managers_exited", sa.Integer(), nullable=False),
        sa.Column("net_managers", sa.Integer(), nullable=False),
        sa.Column("holders", sa.Integer(), nullable=False),
        sa.Column("holders_previous", sa.Integer(), nullable=False),
        sa.Column("shares", sa.Float(), nullable=False),
        sa.Column("shares_previous", sa.Float(), nullable=False),
        sa.Column("split", sa.Text(), nullable=True),
        sa.Column("possible_split", sa.Boolean(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("thirteenf_activity")
    op.drop_table("thirteenf_filing_scale")
    op.drop_table("thirteenf_security_stats")
