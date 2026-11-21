"""Index filings by accession number, to find co-registrants (K-03).

Revision ID: e5c1a7d3f9b2
Revises: d4b6e8f2a9c1
"""

from alembic import op

revision = "e5c1a7d3f9b2"
down_revision = "d4b6e8f2a9c1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index("ix_filings_accession", "filings", ["accession_number"])


def downgrade() -> None:
    op.drop_index("ix_filings_accession", table_name="filings")
