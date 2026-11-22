"""Successor registrants (K-05).

Revision ID: e7b4f2a8c6d1
Revises: d1a7c3e9f5b2
"""

import sqlalchemy as sa
from alembic import op

from app.db.types import UTCDateTime

revision = "e7b4f2a8c6d1"
down_revision = "d1a7c3e9f5b2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "registrant_successions",
        sa.Column("predecessor_cik", sa.String(10), primary_key=True),
        sa.Column("successor_cik", sa.String(10), primary_key=True),
        sa.Column("effective_date", sa.Date(), nullable=False),
        sa.Column("evidence_accession", sa.String(25), nullable=False),
        sa.Column("evidence_form", sa.Text(), nullable=False),
        sa.Column("predecessor_accession", sa.String(25), nullable=True),
        sa.Column("predecessor_form", sa.Text(), nullable=True),
        sa.Column("match_method", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Text(), nullable=False),
        sa.Column("updated_at", UTCDateTime(), nullable=False),
    )
    op.create_index(
        "ix_registrant_successions_successor", "registrant_successions", ["successor_cik"]
    )


def downgrade() -> None:
    op.drop_table("registrant_successions")
