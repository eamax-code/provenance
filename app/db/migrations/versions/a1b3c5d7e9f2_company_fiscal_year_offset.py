"""S-05: each company's fiscal-year naming convention, as its latest 10-K words it.

fiscal_year_offset: years to add to the end-year label (-1 for a company that names its fiscal
year by the calendar year it starts in, as Gap and Target do; 0 where the wording confirms the
end-year name). Null: no wording read (the end-year rule applies).

Revision ID: a1b3c5d7e9f2
Revises: f0a2b4c6d8e1
"""

import sqlalchemy as sa
from alembic import op

revision = "a1b3c5d7e9f2"
down_revision = "f0a2b4c6d8e1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("companies", sa.Column("fiscal_year_offset", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("companies", "fiscal_year_offset")
