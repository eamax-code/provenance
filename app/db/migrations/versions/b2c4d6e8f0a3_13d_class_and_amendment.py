"""Q-07: the class of securities and the amendment number of each structured Schedule 13D, as
filed (the XML's securitiesClassTitle and amendmentNo), beside Item 4.

Revision ID: b2c4d6e8f0a3
Revises: a1b3c5d7e9f2
"""

import sqlalchemy as sa
from alembic import op

revision = "b2c4d6e8f0a3"
down_revision = "a1b3c5d7e9f2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("schedule_13d_purposes", sa.Column("class_title", sa.Text(), nullable=True))
    op.add_column("schedule_13d_purposes",
                  sa.Column("amendment_number", sa.Integer(), nullable=True))  # fmt: skip


def downgrade() -> None:
    op.drop_column("schedule_13d_purposes", "amendment_number")
    op.drop_column("schedule_13d_purposes", "class_title")
