"""D-01b: named_successors, the company a stopped registrant's own filings name as its successor
(display only; figures are never joined). Filled by scripts/find_named_successors.py.

Revision ID: c1e3a5b7d9f2
Revises: b9d1f3a5c7e0
"""

import sqlalchemy as sa
from alembic import op

revision = "c1e3a5b7d9f2"
down_revision = "b9d1f3a5c7e0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "named_successors",
        sa.Column("predecessor_cik", sa.String(10), primary_key=True),
        sa.Column("successor_cik", sa.String(10), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("name_as_filed", sa.Text(), nullable=False),
        sa.Column("quote", sa.Text(), nullable=False),
        sa.Column("match_method", sa.Text(), nullable=False),
        sa.Column("evidence_accession", sa.String(25), nullable=False),
        sa.Column("evidence_form", sa.Text(), nullable=False),
        sa.Column("evidence_date", sa.Date(), nullable=False),
        sa.Column("evidence_url", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("named_successors")
