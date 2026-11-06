"""listed_instruments.issuer_requested: FIRDS IssrReq, the primary-listing signal (ticket 08).

Revision ID: e5b2c8d4a7f3
Revises: d3a9f7c2e5b1
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "e5b2c8d4a7f3"
down_revision = "d3a9f7c2e5b1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("listed_instruments", sa.Column("issuer_requested", sa.Boolean(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("listed_instruments") as batch:
        batch.drop_column("issuer_requested")
