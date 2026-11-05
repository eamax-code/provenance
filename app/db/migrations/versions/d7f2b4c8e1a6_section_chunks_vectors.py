"""Section chunks with embeddings for semantic and hybrid search (issue #2, step 3).

PostgreSQL with pgvector only. One embedding column per model under evaluation, stored as halfvec
(half the memory of float vectors) with an HNSW index for cosine distance, plus a generated tsvector
for keyword search at chunk level. See docs/adr/0008-hybrid-search-in-postgres.md.

Revision ID: d7f2b4c8e1a6
Revises: c5e8a1d3f9b2
"""

from alembic import op

from app.db.search_ddl import CHUNKS_DDL

revision = "d7f2b4c8e1a6"
down_revision = "c5e8a1d3f9b2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute(CHUNKS_DDL)


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute("DROP TABLE IF EXISTS section_chunks")
