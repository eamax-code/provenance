"""Cover-page facts (launch plan D-02): shares outstanding and public float from the latest
10-K or 10-Q cover (dei taxonomy), and the filer category and fiscal year end from the SEC's
company record. Each figure carries the filing it came from.

Auditor name and PCAOB firm ID are not in the SEC's company facts; they come later from PCAOB
Form AP (docs/connections.md item 8).
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Company, FinancialFact
from app.services.point_in_time import known_by

COVER_METRICS = ("shares_outstanding", "public_float")


def _latest(db: Session, cik: str, metric: str, as_of: date | None) -> FinancialFact | None:
    stmt = select(FinancialFact).where(
        FinancialFact.cik == cik,
        FinancialFact.metric == metric,
        FinancialFact.derived.is_(False),
        FinancialFact.quality_status.in_(["ok", "partial"]),
        FinancialFact.value.is_not(None),
    )
    if as_of:
        stmt = known_by(stmt, as_of)
    stmt = stmt.order_by(
        FinancialFact.filed_date.desc().nulls_last(),
        FinancialFact.period_end.desc(),
        FinancialFact.accession_number.desc(),
    )
    return db.scalars(stmt.limit(1)).first()


def cover(db: Session, company: Company, as_of: date | None = None) -> dict:
    out: dict = {
        "filer_category": company.filer_category,
        "fiscal_year_end": company.fiscal_year_end,  # MMDD as the SEC gives it
    }
    for metric in COVER_METRICS:
        f = _latest(db, company.cik, metric, as_of)
        out[metric] = None if f is None else {
            "value": float(f.value),
            "unit": f.unit,
            "as_of_date": f.period_end.isoformat(),
            "form_type": f.form_type,
            "filed_date": f.filed_date.isoformat() if f.filed_date else None,
            "accession_number": f.accession_number,
            "source_url": f.source_url,
        }  # fmt: skip
    return out
