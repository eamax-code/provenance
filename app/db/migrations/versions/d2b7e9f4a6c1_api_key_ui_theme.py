"""The reader's theme in chat and the Explorer, saved with the API key (GH #12).

Revision ID: d2b7e9f4a6c1
Revises: c4f8a1d6e3b7
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "d2b7e9f4a6c1"
down_revision = "c4f8a1d6e3b7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("api_keys", sa.Column("ui_theme", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("api_keys", "ui_theme")
