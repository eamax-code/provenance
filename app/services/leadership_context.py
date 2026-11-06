"""Context for an officer change, from figures known on its filing date (ticket 20).

For the company: revenue growth over the three fiscal years before the change (compound annual)
and the operating margin, with how it moved. If this service recorded the person's appointment
at the company, the same over their tenure. For peers: the median of companies with the same
two-digit SIC code over the same fiscal years.

Point in time: for each period the latest observation filed on or before the change's filing date
(an annual report's first), so nothing known later leaks in and a later restatement is not used.
Every company figure links to its filing. Context is evidence; it says nothing about what the
change will cause (see docs/benchmarks/officer-changes-base-rates-2026-11.md).
"""

from __future__ import annotations

import statistics
from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import Company, FinancialFact, OfficerChange
from app.services import periods
from app.services.fact_normalizer import ANNUAL_FORMS
from app.services.point_in_time import known_by

YEARS = 3
MIN_PEERS = 5
APPOINTED = ("appointment", "election")


def _annual(db: Session, ciks, as_of: date, metrics=("revenue", "operating_income")):
    """{cik: {fiscal_year: {metric: (value, period_end, url)}}}: for each period the latest
    observation filed by as_of, an annual report's over another form's (point in time)."""
    rows = db.execute(
        known_by(
            select(
                FinancialFact.cik,
                FinancialFact.metric,
                FinancialFact.value,
                FinancialFact.period_end,
                FinancialFact.source_url,
                FinancialFact.form_type,
                FinancialFact.filed_date,
                Company.fiscal_year_end,
            )
            .join(Company, Company.cik == FinancialFact.cik)
            .where(
                FinancialFact.cik == ciks if isinstance(ciks, str) else FinancialFact.cik.in_(ciks),
                FinancialFact.metric.in_(metrics),
                FinancialFact.period_class == "annual",
                FinancialFact.unit == "USD",
                FinancialFact.derived.is_(False),
                FinancialFact.quality_status.in_(("ok", "partial")),
                FinancialFact.period_end <= as_of,
                FinancialFact.period_end > as_of - timedelta(days=366 * (YEARS + 3)),
            ),
            as_of,
        )
    ).all()
    best: dict = {}
    for cik, metric, value, end, url, form, filed, fye in rows:
        rank = (form in ANNUAL_FORMS, filed)
        key = (cik, metric, end)
        if key not in best or rank > best[key][0]:
            best[key] = (rank, float(value), url, fye)
    out: dict = {}
    for (cik, metric, end), (_, value, url, fye) in best.items():
        fy = periods.fiscal_year(end, fye)
        out.setdefault(cik, {}).setdefault(fy, {})[metric] = (value, end, url)
    return out


def _cagr(first: float, last: float, years: int) -> float | None:
    if first <= 0 or last <= 0 or years <= 0:
        return None
    return (last / first) ** (1 / years) - 1


def _margin(year: dict) -> float | None:
    rev, op = year.get("revenue"), year.get("operating_income")
    if not rev or not op or rev[0] <= 0:
        return None
    m = op[0] / rev[0]
    return m if abs(m) < 2 else None


def _window(years: dict, first_fy: int, last_fy: int) -> dict | None:
    a, b = years.get(first_fy, {}).get("revenue"), years.get(last_fy, {}).get("revenue")
    if not a or not b:
        return None
    growth = _cagr(a[0], b[0], last_fy - first_fy)
    m0, m1 = _margin(years.get(first_fy, {})), _margin(years.get(last_fy, {}))
    return {
        "fiscal_years": [first_fy, last_fy],
        "revenue_growth_per_year_pct": round(100 * growth, 1) if growth is not None else None,
        "operating_margin_pct": round(100 * m1, 1) if m1 is not None else None,
        "operating_margin_change_pp": round(100 * (m1 - m0), 1)
        if m0 is not None and m1 is not None
        else None,
        "sources": sorted({a[2], b[2]}),
    }


def _appointed_on(db: Session, change: OfficerChange) -> date | None:
    """When this service recorded the person joining the company, if it did."""
    if not change.person or change.change_type in APPOINTED:
        return None
    from app.services.officer_changes import _surname

    surname = _surname(change.person).lower()
    if not surname:
        return None
    rows = db.scalars(
        select(OfficerChange).where(
            OfficerChange.cik == change.cik,
            OfficerChange.change_type.in_(APPOINTED),
            OfficerChange.filing_date < change.filing_date,
            OfficerChange.person.is_not(None),
        )
    ).all()
    starts = [r.filing_date for r in rows if _surname(r.person).lower() == surname]
    return min(starts) if starts else None


def context_for(db: Session, change: OfficerChange) -> dict | None:
    as_of = change.filing_date
    company = db.scalar(select(Company).where(Company.cik == change.cik))
    if as_of is None or company is None:
        return None
    own = _annual(db, change.cik, as_of).get(change.cik, {})
    with_revenue = sorted(fy for fy, v in own.items() if "revenue" in v)
    if not with_revenue:
        return None
    last = with_revenue[-1]
    first = next((fy for fy in with_revenue if fy >= last - YEARS), last)
    context: dict = {
        "as_of": as_of.isoformat(),
        "before_change": _window(own, first, last) if first < last else None,
        "tenure": None,
        "peers": None,
        "note": "Figures as filed on or before the change's filing date. Context only: the "
        "measured base rates show item 5.02 changes say little about what follows.",
    }
    start = _appointed_on(db, change)
    if start is not None:
        start_fy = next((fy for fy in with_revenue if own[fy]["revenue"][1] >= start), None)
        if start_fy is not None and start_fy < last:
            context["tenure"] = {"appointed_filing_date": start.isoformat(),
                                 **_window(own, start_fy, last)}  # fmt: skip
    sic2 = (company.sic_code or "")[:2]
    if sic2 and first < last:
        peer_ciks = select(Company.cik).where(
            func.substr(Company.sic_code, 1, 2) == sic2, Company.cik != change.cik
        )
        peers = _annual(db, peer_ciks, as_of)
        growths, margins = [], []
        for years in peers.values():
            w = _window(years, first, last) if first in years and last in years else None
            if w and w["revenue_growth_per_year_pct"] is not None:
                growths.append(w["revenue_growth_per_year_pct"])
            if w and w["operating_margin_pct"] is not None:
                margins.append(w["operating_margin_pct"])
        if len(growths) >= MIN_PEERS:
            context["peers"] = {
                "group": f"SIC {sic2}",
                "companies": len(growths),
                "fiscal_years": [first, last],
                "median_revenue_growth_per_year_pct": round(statistics.median(growths), 1),
                "median_operating_margin_pct": round(statistics.median(margins), 1)
                if len(margins) >= MIN_PEERS
                else None,
            }
    return context
