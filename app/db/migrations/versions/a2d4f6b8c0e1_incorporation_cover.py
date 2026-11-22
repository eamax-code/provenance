"""The state of incorporation from the company's own cover tag, kept beside the SEC submissions
field instead of replacing it (both are needed: GLEIF can lag a redomicile).

Revision ID: a2d4f6b8c0e1
Revises: f1c7a3e5b9d2
"""

import sqlalchemy as sa
from alembic import op

revision = "a2d4f6b8c0e1"
down_revision = "f1c7a3e5b9d2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("companies", sa.Column("state_of_incorporation_cover", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("companies", "state_of_incorporation_cover")
