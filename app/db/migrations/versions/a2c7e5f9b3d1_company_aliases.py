"""company_aliases: former names a company is found by (issue #3, step 2).

Revision ID: a2c7e5f9b3d1
Revises: f4b8d2a7c3e9
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "a2c7e5f9b3d1"
down_revision = "f4b8d2a7c3e9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "company_aliases",
        sa.Column("cik", sa.String(10), primary_key=True),
        sa.Column("alias", sa.Text(), primary_key=True),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("valid_from", sa.Date(), nullable=True),
        sa.Column("valid_to", sa.Date(), nullable=True),
    )
    op.create_index("ix_company_aliases_lower", "company_aliases", [sa.text("lower(alias)")])


def downgrade() -> None:
    op.drop_index("ix_company_aliases_lower", table_name="company_aliases")
    op.drop_table("company_aliases")
