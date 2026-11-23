"""D-15b: quality_status on Form D filings (suspect_amount for implausible self-reported amounts).

Revision ID: c7e9a1b3d5f8
Revises: b5d7f9a1c3e6
"""

import sqlalchemy as sa
from alembic import op

revision = "c7e9a1b3d5f8"
down_revision = "b5d7f9a1c3e6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("form_d_filings", sa.Column("quality_status", sa.Text(), nullable=False,
                                              server_default="ok"))  # fmt: skip


def downgrade() -> None:
    op.drop_column("form_d_filings", "quality_status")
