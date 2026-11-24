"""Q-02: issuer names as filed on Forms 13F, per security and quarter (most managers' name).

Revision ID: e3f5a7b9c1d2
Revises: d2e4f6a8b0c1
"""

import sqlalchemy as sa
from alembic import op

revision = "e3f5a7b9c1d2"
down_revision = "d2e4f6a8b0c1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "thirteenf_issuer_names",
        sa.Column("cusip", sa.String(9), primary_key=True),
        sa.Column("report_period", sa.Date(), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("managers", sa.Integer(), nullable=False),
        sa.Column("share", sa.Float(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("thirteenf_issuer_names")
