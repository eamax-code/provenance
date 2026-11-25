"""S-07: each company's own fiscal year ends (the year each annual report covers), so a period
is labelled by the year in force when it was filed, not by today's stored fiscal year end.

fiscal_year_ends: ISO dates, comma-separated, oldest first; null until set by
scripts/set_fiscal_year_ends.py (labels then fall back to the stored fiscal year end).

Revision ID: c3d5e7f9a1b4
Revises: b2c4d6e8f0a3
"""

import sqlalchemy as sa
from alembic import op

revision = "c3d5e7f9a1b4"
down_revision = "b2c4d6e8f0a3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("companies", sa.Column("fiscal_year_ends", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("companies", "fiscal_year_ends")
