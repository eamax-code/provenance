"""Full-text search on filing section text (issue #2, step 2).

A stored, generated tsvector column with a GIN index: matching uses the index and ranking reads the
stored vector instead of re-parsing sections that run to 250,000 characters. PostgreSQL only; other
databases skip it, and section search scans in Python there.

Revision ID: b9d4e2f7a6c1
Revises: f1b7c3a9d2e5
"""

from alembic import op

revision = "b9d4e2f7a6c1"
down_revision = "f1b7c3a9d2e5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute(
        "ALTER TABLE filing_sections ADD COLUMN IF NOT EXISTS search_vector tsvector "
        "GENERATED ALWAYS AS (to_tsvector('english'::regconfig, COALESCE(text, ''::text))) STORED"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_filing_sections_search_vector "
        "ON filing_sections USING gin (search_vector)"
    )


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute("DROP INDEX IF EXISTS ix_filing_sections_search_vector")
    op.execute("ALTER TABLE filing_sections DROP COLUMN IF EXISTS search_vector")
