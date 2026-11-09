"""Twelve-month figures in quarterly reports are "ttm", not annual (mapping 1.2.0, issue #9).

Some issuers (Amazon among them) report trailing twelve months to a quarter end in their 10-Qs.
Classified by duration alone they looked like fiscal years: they replaced the annual report's
figures in the marts, mixed fiscal years in rankings and fed derived quarters. 26,521 stored
observations at 432 companies on 2026-11-09. Rebuild the marts and profiles afterwards
(scripts/build_marts.py).

Revision ID: c4f8a1d6e3b7
Revises: b9e5f3a7c1d2
"""

from __future__ import annotations

from alembic import op

revision = "c4f8a1d6e3b7"
down_revision = "b9e5f3a7c1d2"
branch_labels = None
depends_on = None

QUARTERLY = "('10-Q', '10-Q/A', '10-QT', '10-QT/A')"


def upgrade() -> None:
    op.execute(
        "UPDATE financial_facts SET period_class = 'ttm', mapping_version = '1.2.0' "
        f"WHERE period_class = 'annual' AND period_type = 'duration' AND form_type IN {QUARTERLY}"
    )


def downgrade() -> None:
    op.execute(
        "UPDATE financial_facts SET period_class = 'annual', mapping_version = '1.1.0' "
        f"WHERE period_class = 'ttm' AND form_type IN {QUARTERLY}"
    )
