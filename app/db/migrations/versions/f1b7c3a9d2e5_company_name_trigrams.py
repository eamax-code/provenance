"""Trigram index on company names, for typo-tolerant lookup (issue #2, step 1).

PostgreSQL only: other databases (the test suite's SQLite) skip it, and the lookup falls back to a
scan of small tables there.

Revision ID: f1b7c3a9d2e5
Revises: e6a2c9d4b1f8
"""

from alembic import op

revision = "f1b7c3a9d2e5"
down_revision = "e6a2c9d4b1f8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_companies_legal_name_trgm "
        "ON companies USING gin (lower(legal_name) gin_trgm_ops)"
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_companies_ticker_upper ON companies (upper(ticker))")


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute("DROP INDEX IF EXISTS ix_companies_ticker_upper")
    op.execute("DROP INDEX IF EXISTS ix_companies_legal_name_trgm")
