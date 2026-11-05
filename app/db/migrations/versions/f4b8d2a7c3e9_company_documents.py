"""company_documents: readable company profiles, searchable (issue #3).

Revision ID: f4b8d2a7c3e9
Revises: e9a3c6f1b4d8
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from app.db.types import UTCDateTime

revision = "f4b8d2a7c3e9"
down_revision = "e9a3c6f1b4d8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "company_documents",
        sa.Column("cik", sa.String(10), primary_key=True),
        sa.Column("kind", sa.Text(), primary_key=True),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("markdown", sa.Text(), nullable=False),
        sa.Column("built_at", UTCDateTime(), nullable=False),
    )
    if op.get_bind().dialect.name == "postgresql":
        op.execute(
            "ALTER TABLE company_documents ADD COLUMN search_vector tsvector GENERATED ALWAYS AS "
            "(to_tsvector('english'::regconfig, title || ' ' || markdown)) STORED"
        )
        op.execute(
            "CREATE INDEX ix_company_documents_search ON company_documents "
            "USING gin (search_vector)"
        )


def downgrade() -> None:
    op.drop_table("company_documents")
