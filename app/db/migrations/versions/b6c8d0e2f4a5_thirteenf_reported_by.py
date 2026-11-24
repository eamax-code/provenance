"""Q-02: the other managers a 13F names as reporting for it (for 13F notices).

Revision ID: b6c8d0e2f4a5
Revises: a5b7c9d1e3f4
"""

import sqlalchemy as sa
from alembic import op

revision = "b6c8d0e2f4a5"
down_revision = "a5b7c9d1e3f4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "thirteenf_reported_by",
        sa.Column("accession_number", sa.String(25), primary_key=True),
        sa.Column("seq", sa.Integer(), primary_key=True),
        sa.Column("cik", sa.String(10), nullable=True),
        sa.Column("file_number", sa.Text(), nullable=True),
        sa.Column("name", sa.Text(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("thirteenf_reported_by")
