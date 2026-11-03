"""fact observation key unique per company

Parent and subsidiary registrants that file one combined report share an accession number,
so their identical facts have the same observation key; the key is unique per company.

Revision ID: c8e1a4d6f2b7
Revises: b4d2f7a1c9e3
Create Date: 2026-11-03 15:00:00.000000

"""

from __future__ import annotations

from alembic import op

revision = "c8e1a4d6f2b7"
down_revision = "b4d2f7a1c9e3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("financial_facts", schema=None) as batch_op:
        batch_op.drop_constraint("uq_financial_facts_observation_key", type_="unique")
        batch_op.create_unique_constraint(
            "uq_financial_facts_cik_observation_key", ["cik", "observation_key"]
        )


def downgrade() -> None:
    with op.batch_alter_table("financial_facts", schema=None) as batch_op:
        batch_op.drop_constraint("uq_financial_facts_cik_observation_key", type_="unique")
        batch_op.create_unique_constraint("uq_financial_facts_observation_key", ["observation_key"])
