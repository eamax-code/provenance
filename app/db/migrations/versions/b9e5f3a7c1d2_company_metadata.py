"""Company metadata from the SEC submissions: address, phone, filer category, EIN, LEI (#9).

Revision ID: b9e5f3a7c1d2
Revises: a8d4e2c6f9b3
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "b9e5f3a7c1d2"
down_revision = "a8d4e2c6f9b3"
branch_labels = None
depends_on = None

COLUMNS = [
    ("filer_category", sa.Text()),
    ("sec_office", sa.Text()),
    ("ein", sa.String(9)),
    ("lei", sa.String(20)),
    ("phone", sa.Text()),
    ("website", sa.Text()),
    ("investor_website", sa.Text()),
    ("business_address", sa.Text()),
    ("mailing_address", sa.Text()),
    ("tickers", sa.Text()),
    ("exchanges", sa.Text()),
    ("insider_filings_as_issuer", sa.Boolean()),
    ("insider_filings_as_owner", sa.Boolean()),
]


def upgrade() -> None:
    for name, type_ in COLUMNS:
        op.add_column("companies", sa.Column(name, type_, nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("companies") as batch:
        for name, _ in reversed(COLUMNS):
            batch.drop_column(name)
