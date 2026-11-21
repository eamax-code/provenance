"""Normalised name keys on GLEIF entities, other and transliterated names included (K-01c).

Revision ID: f8a2c4e6b0d3
Revises: e5c1a7d3f9b2
"""

import sqlalchemy as sa
from alembic import op

revision = "f8a2c4e6b0d3"
down_revision = "e5c1a7d3f9b2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("gleif_entities", sa.Column("norm_keys", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("gleif_entities", "norm_keys")
