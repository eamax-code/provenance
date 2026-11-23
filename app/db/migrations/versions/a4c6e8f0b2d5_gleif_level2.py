"""D-14 GLEIF Level 2 (relationships, reporting exceptions), names of the LEIs they refer to,
and exhibit 21 subsidiaries linked to LEIs.

Revision ID: a4c6e8f0b2d5
Revises: f3b5d7e9a1c4
"""

import sqlalchemy as sa
from alembic import op

revision = "a4c6e8f0b2d5"
down_revision = "f3b5d7e9a1c4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "gleif_relationships",
        sa.Column("child_lei", sa.String(20), primary_key=True),
        sa.Column("kind", sa.Text(), primary_key=True),
        sa.Column("parent_lei", sa.String(20), nullable=False),
        sa.Column("status", sa.Text(), nullable=True),
        sa.Column("period_start", sa.Date(), nullable=True),
    )
    op.create_index("ix_gleif_relationships_parent", "gleif_relationships", ["parent_lei"])
    op.create_table(
        "gleif_exceptions",
        sa.Column("lei", sa.String(20), primary_key=True),
        sa.Column("kind", sa.Text(), primary_key=True),
        sa.Column("reason", sa.Text(), nullable=False),
    )
    op.create_table(
        "gleif_names",
        sa.Column("lei", sa.String(20), primary_key=True),
        sa.Column("legal_name", sa.Text(), nullable=False),
        sa.Column("jurisdiction", sa.Text(), nullable=True),
        sa.Column("entity_status", sa.Text(), nullable=True),
    )
    op.create_table(
        "subsidiary_leis",
        sa.Column("subsidiary_id", sa.BigInteger(), primary_key=True),
        sa.Column("lei", sa.String(20), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("subsidiary_leis")
    op.drop_table("gleif_names")
    op.drop_table("gleif_exceptions")
    op.drop_table("gleif_relationships")
