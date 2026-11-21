"""Company watches can be limited to filing event types (launch plan D-05).

Revision ID: c4f7a2e9b1d6
Revises: b8e3c1f5d7a2
"""

import sqlalchemy as sa
from alembic import op

revision = "c4f7a2e9b1d6"
down_revision = "b8e3c1f5d7a2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("company_watches", sa.Column("event_types", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("company_watches", "event_types")
