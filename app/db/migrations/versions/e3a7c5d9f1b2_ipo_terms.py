"""IPO deal terms read from prospectuses, each value with its evidence (F-02).

Revision ID: e3a7c5d9f1b2
Revises: d9e2b6f4a8c3
"""

import sqlalchemy as sa
from alembic import op

from app.db.types import UTCDateTime

revision = "e3a7c5d9f1b2"
down_revision = "d9e2b6f4a8c3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ipo_terms",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("cik", sa.String(10), nullable=False),
        sa.Column("accession_number", sa.String(25), nullable=False, unique=True),
        sa.Column("form_type", sa.Text(), nullable=False),
        sa.Column("filing_date", sa.Date()),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("terms", sa.Text(), nullable=False),
        sa.Column("extractor_version", sa.Text(), nullable=False),
        sa.Column("extracted_at", UTCDateTime(), nullable=False),
    )
    op.create_index("ix_ipo_terms_cik", "ipo_terms", ["cik"])


def downgrade() -> None:
    op.drop_index("ix_ipo_terms_cik", table_name="ipo_terms")
    op.drop_table("ipo_terms")
