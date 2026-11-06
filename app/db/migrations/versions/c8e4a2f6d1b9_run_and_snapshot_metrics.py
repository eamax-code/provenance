"""SEC responses by endpoint per run; detection-to-processing percentiles (ticket 11).

Revision ID: c8e4a2f6d1b9
Revises: b6d1f8a4c2e7
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "c8e4a2f6d1b9"
down_revision = "b6d1f8a4c2e7"
branch_labels = None
depends_on = None

SNAPSHOT_COLUMNS = ("detect_to_process_p50_s", "detect_to_process_p95_s", "processed_24h")


def upgrade() -> None:
    op.add_column("ingestion_runs", sa.Column("sec_by_endpoint", sa.Text(), nullable=True))
    for name in SNAPSHOT_COLUMNS:
        op.add_column("data_quality_snapshots", sa.Column(name, sa.Integer(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("data_quality_snapshots") as batch:
        for name in SNAPSHOT_COLUMNS:
            batch.drop_column(name)
    with op.batch_alter_table("ingestion_runs") as batch:
        batch.drop_column("sec_by_endpoint")
