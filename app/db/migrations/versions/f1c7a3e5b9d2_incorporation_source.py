"""Where a company's state of incorporation comes from: its own cover tag
(dei:EntityIncorporationStateCountryCode) and the filing, or the SEC submissions field.

Revision ID: f1c7a3e5b9d2
Revises: e9b3d5f7a1c2
"""

import sqlalchemy as sa
from alembic import op

revision = "f1c7a3e5b9d2"
down_revision = "e9b3d5f7a1c2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("companies", sa.Column("state_of_incorporation_source", sa.Text(), nullable=True))
    op.add_column(
        "companies", sa.Column("state_of_incorporation_accession", sa.String(25), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("companies", "state_of_incorporation_accession")
    op.drop_column("companies", "state_of_incorporation_source")
