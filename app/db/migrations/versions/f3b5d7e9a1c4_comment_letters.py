"""D-13 SEC comment letters and company responses (UPLOAD, CORRESP), read once for tagging.

Revision ID: f3b5d7e9a1c4
Revises: e1a3c5e7f9b2
"""

import sqlalchemy as sa
from alembic import op

revision = "f3b5d7e9a1c4"
down_revision = "e1a3c5e7f9b2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "comment_letters",
        sa.Column("accession_number", sa.String(25), primary_key=True),
        sa.Column("cik", sa.String(10), nullable=False),
        sa.Column("form_type", sa.Text(), nullable=False),
        sa.Column("filing_date", sa.Date(), nullable=False),
        sa.Column("file_number", sa.Text(), nullable=True),
        sa.Column("subject", sa.Text(), nullable=True),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("readable", sa.Boolean(), nullable=False),
        sa.Column("closes_review", sa.Boolean(), nullable=False),
        sa.Column("topics", sa.Text(), nullable=False),
        sa.Column("text", sa.Text(), nullable=True),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("reader_version", sa.Text(), nullable=False),
    )
    op.create_index("ix_comment_letters_cik_filed", "comment_letters", ["cik", "filing_date"])


def downgrade() -> None:
    op.drop_table("comment_letters")
