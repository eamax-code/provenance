"""The filing a company's legal name as filed comes from (K-06).

Revision ID: d5a1c7e3f8b6
Revises: c3f8a2d6e9b4
"""

import sqlalchemy as sa
from alembic import op

revision = "d5a1c7e3f8b6"
down_revision = "c3f8a2d6e9b4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("companies", sa.Column("registrant_name_accession", sa.String(25), nullable=True))


def downgrade() -> None:
    op.drop_column("companies", "registrant_name_accession")
