"""Accounts, one-time sign-in links and browser sessions (GH #15).

Revision ID: e6a3c9d1f5b8
Revises: d2b7e9f4a6c1
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from app.db.types import UTCDateTime

revision = "e6a3c9d1f5b8"
down_revision = "d2b7e9f4a6c1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "accounts",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("email", sa.Text(), nullable=False, unique=True),
        sa.Column("created_at", UTCDateTime(), nullable=False),
        sa.Column("last_sign_in_at", UTCDateTime(), nullable=True),
        sa.Column("ui_theme", sa.Text(), nullable=True),
    )
    op.create_table(
        "sign_in_tokens",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("email", sa.Text(), nullable=False),
        sa.Column("token_hash", sa.Text(), nullable=False, unique=True),
        sa.Column("created_at", UTCDateTime(), nullable=False),
        sa.Column("expires_at", UTCDateTime(), nullable=False),
        sa.Column("used_at", UTCDateTime(), nullable=True),
    )
    op.create_index("ix_sign_in_tokens_email_created", "sign_in_tokens", ["email", "created_at"])
    op.create_table(
        "account_sessions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("account_id", sa.Uuid(), sa.ForeignKey("accounts.id"), nullable=False),
        sa.Column("token_hash", sa.Text(), nullable=False, unique=True),
        sa.Column("created_at", UTCDateTime(), nullable=False),
        sa.Column("expires_at", UTCDateTime(), nullable=False),
        sa.Column("last_seen_at", UTCDateTime(), nullable=True),
        sa.Column("revoked_at", UTCDateTime(), nullable=True),
    )
    op.create_index("ix_account_sessions_account", "account_sessions", ["account_id"])


def downgrade() -> None:
    op.drop_index("ix_account_sessions_account", table_name="account_sessions")
    op.drop_table("account_sessions")
    op.drop_index("ix_sign_in_tokens_email_created", table_name="sign_in_tokens")
    op.drop_table("sign_in_tokens")
    op.drop_table("accounts")
