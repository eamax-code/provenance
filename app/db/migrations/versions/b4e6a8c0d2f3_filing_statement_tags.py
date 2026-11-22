"""Revenue tags each filing places on its income statement, with the filing's own labels
(mapping 1.5.0: the income-statement line as the tie-breaker; IFRS bank total income).

Revision ID: b4e6a8c0d2f3
Revises: a2d4f6b8c0e1
"""

import sqlalchemy as sa
from alembic import op

revision = "b4e6a8c0d2f3"
down_revision = "a2d4f6b8c0e1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "filing_statement_tags",
        sa.Column("accession_number", sa.String(25), primary_key=True),
        sa.Column("tag", sa.Text(), primary_key=True),
        sa.Column("cik", sa.String(10), nullable=False),
        sa.Column("label", sa.Text(), nullable=False),
        sa.Column("line", sa.Integer(), nullable=True),
        sa.Column("source", sa.Text(), nullable=False),
    )
    op.create_index("ix_filing_statement_tags_cik", "filing_statement_tags", ["cik"])


def downgrade() -> None:
    op.drop_index("ix_filing_statement_tags_cik", "filing_statement_tags")
    op.drop_table("filing_statement_tags")
