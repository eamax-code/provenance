"""Type watches: filing event types across companies, with an optional universe (T-01).

Revision ID: d9e2b6f4a8c3
Revises: c4f7a2e9b1d6
"""

import sqlalchemy as sa
from alembic import op

from app.db.types import UTCDateTime

revision = "d9e2b6f4a8c3"
down_revision = "c4f7a2e9b1d6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "type_watches",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("api_key_id", sa.Uuid(), sa.ForeignKey("api_keys.id"), nullable=False),
        sa.Column("event_types", sa.Text(), nullable=False),
        sa.Column("sic_prefix", sa.Text()),
        sa.Column("exchange", sa.Text()),
        sa.Column("filer_category", sa.Text()),
        sa.Column("ciks", sa.Text()),
        sa.Column("delivery_mode", sa.Text(), nullable=False),
        sa.Column("destination_type", sa.Text(), nullable=False),
        sa.Column("destination", sa.Text(), nullable=False),
        sa.Column("secret_hash", sa.Text()),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", UTCDateTime(), nullable=False),
        sa.Column("deactivated_at", UTCDateTime()),
        sa.Column("last_delivered_at", UTCDateTime()),
    )
    op.create_index("ix_type_watches_active", "type_watches", ["is_active"])
    with op.batch_alter_table("notification_deliveries") as batch:
        batch.add_column(sa.Column("type_watch_id", sa.Uuid(), nullable=True))
        batch.create_foreign_key(
            "fk_deliveries_type_watch", "type_watches", ["type_watch_id"], ["id"]
        )


def downgrade() -> None:
    with op.batch_alter_table("notification_deliveries") as batch:
        batch.drop_constraint("fk_deliveries_type_watch", type_="foreignkey")
        batch.drop_column("type_watch_id")
    op.drop_index("ix_type_watches_active", table_name="type_watches")
    op.drop_table("type_watches")
