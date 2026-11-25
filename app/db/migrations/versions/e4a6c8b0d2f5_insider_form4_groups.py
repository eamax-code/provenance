"""Q-03f: insider_form4_groups, the insider screener's open-market lines added up per Form 4,
issuer, code, security class and plan bucket. Filled by scripts/build_insider_groups.py, then kept
by insiders.store and the plan-purchase flags.

Revision ID: e4a6c8b0d2f5
Revises: d3f5b7c9e1a4
"""

import sqlalchemy as sa
from alembic import op

revision = "e4a6c8b0d2f5"
down_revision = "d3f5b7c9e1a4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "insider_form4_groups",
        sa.Column("accession_number", sa.String(25), primary_key=True),
        sa.Column("issuer_cik", sa.String(10), primary_key=True),
        sa.Column("trans_code", sa.String(4), primary_key=True),
        sa.Column("title", sa.Text(), primary_key=True),
        sa.Column("plan_bucket", sa.Boolean(), primary_key=True),
        sa.Column("first_date", sa.Date(), nullable=False),
        sa.Column("last_date", sa.Date(), nullable=False),
        sa.Column("lines", sa.Integer(), nullable=False),
        sa.Column("shares", sa.Numeric(), nullable=True),
        sa.Column("value", sa.Numeric(), nullable=True),
        sa.Column("priced_shares", sa.Numeric(), nullable=True),
        sa.Column("priced_lines", sa.Integer(), nullable=False),
        sa.Column("di_min", sa.String(1), nullable=True),
        sa.Column("di_max", sa.String(1), nullable=True),
        sa.Column("plan_lines", sa.Integer(), nullable=False),
        sa.Column("inferred_lines", sa.Integer(), nullable=False),
    )
    op.create_index("ix_insider_form4_groups_code_last", "insider_form4_groups",
                    ["trans_code", "last_date"])  # fmt: skip


def downgrade() -> None:
    op.drop_index("ix_insider_form4_groups_code_last", table_name="insider_form4_groups")
    op.drop_table("insider_form4_groups")
