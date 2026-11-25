"""Q-03g: near_median and near_count on insider_form4_groups (the price-outlier flag's median,
precomputed with the groups). Filled by scripts/build_insider_groups.py.

Revision ID: f6c8e0a2b4d7
Revises: e4a6c8b0d2f5
"""

import sqlalchemy as sa
from alembic import op

revision = "f6c8e0a2b4d7"
down_revision = "e4a6c8b0d2f5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("insider_form4_groups", sa.Column("near_median", sa.Float(), nullable=True))
    op.add_column("insider_form4_groups", sa.Column("near_count", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("insider_form4_groups", "near_count")
    op.drop_column("insider_form4_groups", "near_median")
