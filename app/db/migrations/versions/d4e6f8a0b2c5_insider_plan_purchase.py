"""F-03f: insider_transactions.plan_purchase, true for a code-P line bought under an employee or
director stock purchase plan, a plan trust or dividend reinvestment (its ownership text or its
own footnotes say so). Such lines are never part of cluster buying or a first buy.

Null until scripts/flag_plan_purchases.py fills it (then set at parse time); null on other codes.

Revision ID: d4e6f8a0b2c5
Revises: c3d5e7f9a1b4
"""

import sqlalchemy as sa
from alembic import op

revision = "d4e6f8a0b2c5"
down_revision = "c3d5e7f9a1b4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("insider_transactions", sa.Column("plan_purchase", sa.Boolean(), nullable=True))


def downgrade() -> None:
    op.drop_column("insider_transactions", "plan_purchase")
