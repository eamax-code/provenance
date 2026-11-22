"""X-07 watchlists: named lists of companies with chosen columns, stored per API key.

Revision ID: d8f0a2c4e6b1
Revises: c6e8a0b2d4f5
"""

import sqlalchemy as sa
from alembic import op

from app.db.types import UTCDateTime

revision = "d8f0a2c4e6b1"
down_revision = "c6e8a0b2d4f5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "watchlists",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("api_key_id", sa.Uuid(), sa.ForeignKey("api_keys.id"), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("columns", sa.Text(), nullable=False),
        sa.Column("created_at", UTCDateTime(), nullable=False),
        sa.Column("updated_at", UTCDateTime(), nullable=False),
    )
    op.create_index("ix_watchlists_api_key_id", "watchlists", ["api_key_id"])
    op.create_table(
        "watchlist_companies",
        sa.Column(
            "watchlist_id",
            sa.Uuid(),
            sa.ForeignKey("watchlists.id", ondelete="CASCADE"),
            primary_key=True,
        ),  # fmt: skip
        sa.Column("cik", sa.String(10), primary_key=True),
        sa.Column("position", sa.Integer(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("watchlist_companies")
    op.drop_index("ix_watchlists_api_key_id", table_name="watchlists")
    op.drop_table("watchlists")
