"""F-03d: who signed a Form 3/4/5 with an entity reporting owner, its remarks and footnotes,
for linking an individual to the fund he controls (cluster buyers).

Revision ID: d8e0f2a4b6c7
Revises: c7d9e1f3a5b6
"""

import sqlalchemy as sa
from alembic import op

revision = "d8e0f2a4b6c7"
down_revision = "c7d9e1f3a5b6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "insider_filing_text",
        sa.Column("accession_number", sa.String(25), primary_key=True),
        sa.Column("signatures", sa.Text(), nullable=False),  # JSON list, as signed
        sa.Column("remarks", sa.Text(), nullable=True),
        sa.Column("footnotes", sa.Text(), nullable=False),  # JSON list of the footnote texts
        sa.Column("source", sa.Text(), nullable=False),  # "dataset:2026q3"
    )


def downgrade() -> None:
    op.drop_table("insider_filing_text")
