"""Event types a filing's form alone cannot tell, such as an IPO priced (F-02).

Revision ID: f6b1d8e4a2c7
Revises: e3a7c5d9f1b2
"""

import sqlalchemy as sa
from alembic import op

revision = "f6b1d8e4a2c7"
down_revision = "e3a7c5d9f1b2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("filings", sa.Column("event_tags", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("filings", "event_tags")
