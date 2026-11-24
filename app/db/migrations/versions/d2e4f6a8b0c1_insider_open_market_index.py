"""Q-03: index on the transaction date of open-market lines (codes P and S, table I) for the
cross-company insider screener; the issuer-and-date index made a 30-day screen take 560 ms.

Revision ID: d2e4f6a8b0c1
Revises: c7e9a1b3d5f8
"""

from alembic import op

revision = "d2e4f6a8b0c1"
down_revision = "c7e9a1b3d5f8"
branch_labels = None
depends_on = None

NAME = "ix_insider_transactions_open_market"
WHERE = "trans_code IN ('P', 'S') AND NOT is_derivative"


def upgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        with op.get_context().autocommit_block():  # built without locking the insider loads
            op.execute(f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {NAME} "
                       f"ON insider_transactions (trans_date) WHERE {WHERE}")  # fmt: skip
    else:
        op.execute(f"CREATE INDEX IF NOT EXISTS {NAME} "
                   f"ON insider_transactions (trans_date) WHERE {WHERE}")  # fmt: skip


def downgrade() -> None:
    op.execute(f"DROP INDEX IF EXISTS {NAME}")
