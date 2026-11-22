"""Marts in each company's reporting currency (D-04).

Revision ID: a6d2e8f4c0b3
Revises: f2c8a4e6b1d7
"""

import sqlalchemy as sa
from alembic import op

revision = "a6d2e8f4c0b3"
down_revision = "f2c8a4e6b1d7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("mart_company", sa.Column("reporting_currency", sa.Text(), nullable=True))
    op.add_column("mart_company_period", sa.Column("currency", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("mart_company_period", "currency")
    op.drop_column("mart_company", "reporting_currency")
