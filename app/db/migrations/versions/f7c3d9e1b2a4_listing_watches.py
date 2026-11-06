"""listing_watches, and deliveries for listing events (ticket 09).

Revision ID: f7c3d9e1b2a4
Revises: e5b2c8d4a7f3
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from app.db.types import UTCDateTime

revision = "f7c3d9e1b2a4"
down_revision = "e5b2c8d4a7f3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "listing_watches",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("api_key_id", sa.Uuid(), sa.ForeignKey("api_keys.id"), nullable=False),
        sa.Column("scope_type", sa.Text(), nullable=False),
        sa.Column("scope_value", sa.Text(), nullable=False),
        sa.Column("event_types", sa.Text(), nullable=False),
        sa.Column("destination_type", sa.Text(), nullable=False),
        sa.Column("destination", sa.Text(), nullable=False),
        sa.Column("secret_hash", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", UTCDateTime(), nullable=False),
        sa.Column("deactivated_at", UTCDateTime(), nullable=True),
        sa.Column("last_delivered_at", UTCDateTime(), nullable=True),
    )
    op.create_index(
        "ix_listing_watches_scope_active",
        "listing_watches",
        ["scope_type", "scope_value", "is_active"],
    )
    with op.batch_alter_table("notification_deliveries") as batch:
        batch.alter_column("watch_id", existing_type=sa.Uuid(), nullable=True)
        batch.alter_column("filing_id", existing_type=sa.Uuid(), nullable=True)
        batch.add_column(sa.Column("listing_watch_id", sa.Uuid(), nullable=True))
        batch.add_column(sa.Column("listing_event_id", sa.Uuid(), nullable=True))
        batch.create_foreign_key(
            "fk_deliveries_listing_watch", "listing_watches", ["listing_watch_id"], ["id"]
        )
        batch.create_foreign_key(
            "fk_deliveries_listing_event", "listing_events", ["listing_event_id"], ["id"]
        )


def downgrade() -> None:
    op.execute("DELETE FROM notification_deliveries WHERE listing_watch_id IS NOT NULL")
    with op.batch_alter_table("notification_deliveries") as batch:
        batch.drop_constraint("fk_deliveries_listing_event", type_="foreignkey")
        batch.drop_constraint("fk_deliveries_listing_watch", type_="foreignkey")
        batch.drop_column("listing_event_id")
        batch.drop_column("listing_watch_id")
        batch.alter_column("filing_id", existing_type=sa.Uuid(), nullable=False)
        batch.alter_column("watch_id", existing_type=sa.Uuid(), nullable=False)
    op.drop_index("ix_listing_watches_scope_active", table_name="listing_watches")
    op.drop_table("listing_watches")
