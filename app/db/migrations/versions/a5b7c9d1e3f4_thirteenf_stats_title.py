"""Q-02: the class title most managers give a security in a quarter, so one security has one
class label for portfolios and the activity list alike.

Revision ID: a5b7c9d1e3f4
Revises: f4a6b8c0d2e3
"""

import sqlalchemy as sa
from alembic import op

revision = "a5b7c9d1e3f4"
down_revision = "f4a6b8c0d2e3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("thirteenf_security_stats", sa.Column("title", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("thirteenf_security_stats", "title")
