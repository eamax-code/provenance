"""Q-09: filing_sections.filed_text (a 10-K item as filed: the document's paragraphs joined by a
blank line, no markers) and layout (JSON: heading as filed, start and end offsets in the
document's text as read, subheadings' offsets, the document's name). Null until set by
scripts/locate_10k_sections.py, then set when an item is read.

Revision ID: a8c0e2f4b6d9
Revises: f6a8b0c2d4e7
"""

import sqlalchemy as sa
from alembic import op

revision = "a8c0e2f4b6d9"
down_revision = "f6a8b0c2d4e7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("filing_sections", sa.Column("filed_text", sa.Text(), nullable=True))
    op.add_column("filing_sections", sa.Column("layout", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("filing_sections", "layout")
    op.drop_column("filing_sections", "filed_text")
