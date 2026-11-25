"""F-03g: insider_transactions.plan_inferred, true for a code-P line whose filing does not state a
plan but whose shares are a fraction under 100 (dividend reinvestment, a plan or a fund
subscription in a check of 30). Never plan_purchase, which means stated. Such lines are never
part of cluster buying or a first buy.

Revision ID: e5f7a9b1c3d6
Revises: d4e6f8a0b2c5
"""

import sqlalchemy as sa
from alembic import op

revision = "e5f7a9b1c3d6"
down_revision = "d4e6f8a0b2c5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("insider_transactions", sa.Column("plan_inferred", sa.Boolean(), nullable=True))


def downgrade() -> None:
    op.drop_column("insider_transactions", "plan_inferred")
