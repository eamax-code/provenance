"""Q-03e: index on the filing date of Form 4/As, for the insider screener's list of the 4/As
filed since a date (a sequential scan of 1.1M filings took about 35 ms per value-filtered screen).

Revision ID: d3f5b7c9e1a4
Revises: c1e3a5b7d9f2
"""

from alembic import op

revision = "d3f5b7c9e1a4"
down_revision = "c1e3a5b7d9f2"
branch_labels = None
depends_on = None

NAME = "ix_insider_filings_amendment_date"
WHERE = "form_type = '4/A'"


def upgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        with op.get_context().autocommit_block():  # built without locking the insider loads
            op.execute(f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {NAME} "
                       f"ON insider_filings (filing_date) WHERE {WHERE}")  # fmt: skip
    else:
        op.execute(f"CREATE INDEX IF NOT EXISTS {NAME} "
                   f"ON insider_filings (filing_date) WHERE {WHERE}")  # fmt: skip


def downgrade() -> None:
    op.execute(f"DROP INDEX IF EXISTS {NAME}")
