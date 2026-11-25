"""D-01: mart_company.periodic_active (a 10-K, 10-Q, 20-F or 40-F under the company's own CIK
within 18 months), last_periodic_date and last_periodic_form. Set by the marts build
(scripts/build_marts.py); false until then.

Revision ID: b9d1f3a5c7e0
Revises: a8c0e2f4b6d9
"""

import sqlalchemy as sa
from alembic import op

revision = "b9d1f3a5c7e0"
down_revision = "a8c0e2f4b6d9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "mart_company",
        sa.Column("periodic_active", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column("mart_company", sa.Column("last_periodic_date", sa.Date(), nullable=True))
    op.add_column("mart_company", sa.Column("last_periodic_form", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("mart_company", "last_periodic_form")
    op.drop_column("mart_company", "last_periodic_date")
    op.drop_column("mart_company", "periodic_active")
