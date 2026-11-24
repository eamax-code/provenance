"""Point-in-time views of facts: only what had been filed with the SEC by a given date."""

from __future__ import annotations

from datetime import date

from sqlalchemy import and_, exists, or_

from app.db.models import FinancialFact, FirstReported

AS_OF_NOTE = (
    "Point in time as of {as_of}: only observations filed on or before that date are used, and "
    "revision_count counts only revisions known by then. filed_date is a date without a time, so "
    "a filing accepted after the market closed on {as_of} is included; use the previous day for "
    "a strict backtest. A figure an earnings release stated earlier (first_reported) counts "
    "from the release date."
)


def known_by(stmt, as_of: date, model=FinancialFact):
    """Restrict a FinancialFact query to observations filed with the SEC on or before as_of.

    Observations without a filing date are excluded: when they became known cannot be shown.
    A figure an 8-K 2.02 earnings release stated with the same value (E-2) counts from the
    release's filing date. model: FinancialFact, or DividendFact (Q-04; the same columns).
    """
    F = model
    stated_earlier = exists().where(
        and_(
            FirstReported.fact_accession == F.accession_number,
            FirstReported.metric == F.metric,
            FirstReported.unit == F.unit,
            FirstReported.period_end == F.period_end,
            FirstReported.period_start.is_not_distinct_from(F.period_start),
            FirstReported.release_filing_date <= as_of,
        )
    )
    return stmt.where(
        F.filed_date.is_not(None),
        or_(F.filed_date <= as_of, stated_earlier),
    )


def as_of_note(as_of: date) -> str:
    return AS_OF_NOTE.format(as_of=as_of.isoformat())
