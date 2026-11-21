"""GLEIF golden-copy entities whose legal name matches an SEC filer (K-01b).

Revision ID: d4b6e8f2a9c1
Revises: c7e3a9b5d2f8
"""

import sqlalchemy as sa
from alembic import op

from app.db.types import UTCDateTime

revision = "d4b6e8f2a9c1"
down_revision = "c7e3a9b5d2f8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "gleif_entities",
        sa.Column("lei", sa.String(20), primary_key=True),
        sa.Column("legal_name", sa.Text(), nullable=False),
        sa.Column("name_key", sa.Text(), nullable=False),
        sa.Column("jurisdiction", sa.Text()),
        sa.Column("entity_status", sa.Text()),
        sa.Column("registration_status", sa.Text()),
        sa.Column("loaded_at", UTCDateTime(), nullable=False),
    )
    op.create_index("ix_gleif_entities_key", "gleif_entities", ["name_key"])


def downgrade() -> None:
    op.drop_index("ix_gleif_entities_key", table_name="gleif_entities")
    op.drop_table("gleif_entities")
