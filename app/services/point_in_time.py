"""Point-in-time views of facts: only what had been filed with the SEC by a given date."""

from __future__ import annotations

from datetime import date

from app.db.models import FinancialFact

AS_OF_NOTE = (
    "Point in time as of {as_of}: only observations filed on or before that date are used, and "
    "revision_count counts only revisions known by then. filed_date is a date without a time, so "
    "a filing accepted after the market closed on {as_of} is included; use the previous day for "
    "a strict backtest."
)


def known_by(stmt, as_of: date):
    """Restrict a FinancialFact query to observations filed with the SEC on or before as_of.

    Observations without a filing date are excluded: when they became known cannot be shown.
    """
    return stmt.where(FinancialFact.filed_date.is_not(None), FinancialFact.filed_date <= as_of)


def as_of_note(as_of: date) -> str:
    return AS_OF_NOTE.format(as_of=as_of.isoformat())
