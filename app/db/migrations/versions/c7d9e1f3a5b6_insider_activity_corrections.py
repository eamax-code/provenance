"""F-03c: insider activity events can be retracted or corrected, never silently deleted.

status is "active" or "retracted" (retracted_at, retraction_reason); a corrected event keeps
what it said before in previous_values (JSON) with corrected_at.

Revision ID: c7d9e1f3a5b6
Revises: b6c8d0e2f4a5
"""

import sqlalchemy as sa
from alembic import op

from app.db.types import UTCDateTime

revision = "c7d9e1f3a5b6"
down_revision = "b6c8d0e2f4a5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("insider_activity", sa.Column("status", sa.Text(), nullable=False,
                                                server_default="active"))  # fmt: skip
    op.add_column("insider_activity", sa.Column("retracted_at", UTCDateTime()))
    op.add_column("insider_activity", sa.Column("retraction_reason", sa.Text()))
    op.add_column("insider_activity", sa.Column("corrected_at", UTCDateTime()))
    op.add_column("insider_activity", sa.Column("previous_values", sa.Text()))


def downgrade() -> None:
    for c in ("previous_values", "corrected_at", "retraction_reason", "retracted_at", "status"):
        op.drop_column("insider_activity", c)
