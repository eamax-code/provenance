"""Seconds from SEC acceptance to first detection, on quality snapshots (pilot status page).

Revision ID: f3b8d2a7c4e9
Revises: e6a3c9d1f5b8
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "f3b8d2a7c4e9"
down_revision = "e6a3c9d1f5b8"
branch_labels = None
depends_on = None

COLUMNS = ("accept_to_detect_p50_s", "accept_to_detect_p95_s")


def upgrade() -> None:
    for name in COLUMNS:
        op.add_column("data_quality_snapshots", sa.Column(name, sa.Integer(), nullable=True))


def downgrade() -> None:
    for name in COLUMNS:
        op.drop_column("data_quality_snapshots", name)
