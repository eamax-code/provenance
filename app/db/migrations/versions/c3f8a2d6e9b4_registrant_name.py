"""Company name as written on its own cover page (K-06).

Revision ID: c3f8a2d6e9b4
Revises: b7e3f9a1d5c2
"""

import sqlalchemy as sa
from alembic import op

revision = "c3f8a2d6e9b4"
down_revision = "b7e3f9a1d5c2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("companies", sa.Column("registrant_name", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("companies", "registrant_name")
