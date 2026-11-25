"""Q-06: fails_to_deliver (the SEC's fails-to-deliver for CUSIPs mapped to a company here; the
CUSIP is never returned) and ftd_files (each file loaded, with its publication date for as_of).

Revision ID: f6a8b0c2d4e7
Revises: e5f7a9b1c3d6
"""

import sqlalchemy as sa
from alembic import op

revision = "f6a8b0c2d4e7"
down_revision = "e5f7a9b1c3d6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "fails_to_deliver",
        sa.Column("cusip", sa.String(9), primary_key=True),
        sa.Column("settlement_date", sa.Date(), primary_key=True),
        sa.Column("cik", sa.String(10), nullable=False),
        sa.Column("symbol", sa.Text(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("quantity", sa.BigInteger(), nullable=False),
        sa.Column("price", sa.Numeric(24, 6), nullable=True),
        sa.Column("source_file", sa.Text(), nullable=False),
    )
    op.create_index("ix_fails_to_deliver_cik_date", "fails_to_deliver", ["cik", "settlement_date"])
    op.create_table(
        "ftd_files",
        sa.Column("name", sa.Text(), primary_key=True),
        sa.Column("published", sa.Date(), nullable=False),
        sa.Column("first_date", sa.Date(), nullable=True),
        sa.Column("last_date", sa.Date(), nullable=True),
        sa.Column("rows", sa.Integer(), nullable=False),
        sa.Column("matched", sa.Integer(), nullable=False),
        sa.Column("loaded_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("ftd_files")
    op.drop_index("ix_fails_to_deliver_cik_date", table_name="fails_to_deliver")
    op.drop_table("fails_to_deliver")
