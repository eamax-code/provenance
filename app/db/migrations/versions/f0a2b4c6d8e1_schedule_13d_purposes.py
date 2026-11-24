"""Q-07: Item 4 (Purpose of Transaction) of structured Schedules 13D and 13D/A, as filed.

Revision ID: f0a2b4c6d8e1
Revises: e9f1a3b5c7d9
"""

import sqlalchemy as sa
from alembic import op

revision = "f0a2b4c6d8e1"
down_revision = "e9f1a3b5c7d9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "schedule_13d_purposes",
        sa.Column("accession_number", sa.String(25), primary_key=True),
        sa.Column("subject_cik", sa.String(10), nullable=False),
        sa.Column("purpose", sa.Text(), nullable=True),  # null: the filing leaves Item 4 out
        sa.Column("source_url", sa.Text(), nullable=False),  # the XML on Archives
    )
    op.create_index("ix_schedule_13d_purposes_subject", "schedule_13d_purposes", ["subject_cik"])


def downgrade() -> None:
    op.drop_index("ix_schedule_13d_purposes_subject", table_name="schedule_13d_purposes")
    op.drop_table("schedule_13d_purposes")
