"""Covering screen index on mart_financials: value included (issue #3).

Revision ID: b6d1f8a4c2e7
Revises: a2c7e5f9b3d1
"""

from __future__ import annotations

from alembic import op

revision = "b6d1f8a4c2e7"
down_revision = "a2c7e5f9b3d1"
branch_labels = None
depends_on = None

COLUMNS = ["metric", "period_class", "unit", "period_end", "cik"]


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.drop_index("ix_mart_financials_screen", table_name="mart_financials")
    op.create_index(
        "ix_mart_financials_screen", "mart_financials", COLUMNS, postgresql_include=["value"]
    )


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.drop_index("ix_mart_financials_screen", table_name="mart_financials")
    op.create_index("ix_mart_financials_screen", "mart_financials", COLUMNS)
