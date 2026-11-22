"""Headquarters and legal-address cities on GLEIF entities (K-01d: address evidence for a match
whose US state differs between the SEC and GLEIF).

Revision ID: e9b3d5f7a1c2
Revises: d5a1c7e3f8b6
"""

import sqlalchemy as sa
from alembic import op

revision = "e9b3d5f7a1c2"
down_revision = "d5a1c7e3f8b6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("gleif_entities", sa.Column("hq_city", sa.Text(), nullable=True))
    op.add_column("gleif_entities", sa.Column("hq_region", sa.Text(), nullable=True))
    op.add_column("gleif_entities", sa.Column("legal_city", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("gleif_entities", "legal_city")
    op.drop_column("gleif_entities", "hq_region")
    op.drop_column("gleif_entities", "hq_city")
