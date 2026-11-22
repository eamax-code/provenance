"""Federal Reserve H.10 daily exchange rates (public domain), a reference table used only to
place companies in USD-equivalent size cohorts; never shown as a company's figure.

Revision ID: c6e8a0b2d4f5
Revises: b4e6a8c0d2f3
"""

import sqlalchemy as sa
from alembic import op

revision = "c6e8a0b2d4f5"
down_revision = "b4e6a8c0d2f3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "fx_rates",
        sa.Column("currency", sa.String(3), primary_key=True),
        sa.Column("rate_date", sa.Date(), primary_key=True),
        sa.Column("value", sa.Numeric(20, 8), nullable=False),
        sa.Column("usd_per_unit", sa.Boolean(), nullable=False),
        sa.Column("series_id", sa.Text(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("fx_rates")
