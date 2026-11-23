"""X-15: a calendar of dated items per company (docs/contracts/calendar.md).

Derived items say derived and give their rule in `basis`:
* filing deadlines from the filer category and each report's own period end (past periods) or
  the periods projected from the latest report (future ones);
* IPO lock-up ends and research quiet-period ends from the final prospectus;
* the end of a Form 144 notice's 90 days when no matching sale is reported.
Late notices (NT 10-K, NT 10-Q, NT 20-F) are filings, not derived. Stored data only.
"""

from __future__ import annotations

import json
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Company, Filing, IpoTerms
from app.services.intel import display_name

KINDS = ("filing_deadline", "late_notice", "lockup_expiry", "quiet_period_end",
         "annual_meeting", "proposed_sale_window_end")  # fmt: skip
MAX_RANGE_DAYS = 400
WATCHLIST_CAP = 500
NOTES = ["Derived dates are computed from rules and the company's own filings; the company's "
         "actual filing date can differ. A due date on a weekend or US federal holiday moves to "
         "the next business day."]  # fmt: skip
ANNUAL, QUARTERLY = ("10-K", "10-K/A", "10-KT"), ("10-Q", "10-Q/A")
LATE = ("NT 10-K", "NT 10-Q", "NT 20-F", "NT 10-K/A", "NT 10-Q/A")
# (10-K days, 10-Q days, the rule's name)
DAYS = {
    "large": (60, 40, "Large accelerated filer"),
    "accelerated": (75, 40, "Accelerated filer"),
    "other": (90, 45, "Non-accelerated filer"),
}


def category(filer_category: str | None) -> str | None:
    """large, accelerated or other from the SEC's filer status; None when it does not say."""
    c = (filer_category or "").lower()
    if "large accelerated" in c:
        return "large"
    if "non-accelerated" in c:
        return "other"
    if "accelerated" in c:
        return "accelerated"
    return None


# -- business days ------------------------------------------------------------------------


def _nth(year: int, month: int, weekday: int, n: int) -> date:
    d = date(year, month, 1)
    d += timedelta(days=(weekday - d.weekday()) % 7)
    return d + timedelta(weeks=n - 1)


def _last(year: int, month: int, weekday: int) -> date:
    d = date(year, month + 1, 1) - timedelta(days=1) if month < 12 else date(year, 12, 31)
    return d - timedelta(days=(d.weekday() - weekday) % 7)


def _observed(d: date) -> date:
    return d - timedelta(days=1) if d.weekday() == 5 else d + timedelta(days=1) if \
        d.weekday() == 6 else d  # fmt: skip


def federal_holidays(year: int) -> set[date]:
    fixed = [date(year, 1, 1), date(year, 6, 19), date(year, 7, 4), date(year, 11, 11),
             date(year, 12, 25)]  # fmt: skip
    return {_observed(d) for d in fixed} | {
        _nth(year, 1, 0, 3), _nth(year, 2, 0, 3), _last(year, 5, 0), _nth(year, 9, 0, 1),
        _nth(year, 10, 0, 2), _nth(year, 11, 3, 4),
    }  # fmt: skip


def next_business_day(d: date) -> date:
    hol = federal_holidays(d.year) | federal_holidays(d.year + 1)
    while d.weekday() >= 5 or d in hol:
        d += timedelta(days=1)
    return d


def _add_months(d: date, months: int) -> date:
    m = d.month - 1 + months
    y, m = d.year + m // 12, m % 12 + 1
    last = (date(y + (m == 12), m % 12 + 1, 1) - timedelta(days=1)).day
    # a month-end period stays a month-end period
    month_end = d == (date(d.year + (d.month == 12), d.month % 12 + 1, 1) - timedelta(days=1))
    return date(y, m, last if month_end else min(d.day, last))


# -- items ----------------------------------------------------------------------------------


def _src(f, why: str | None = None) -> dict:
    out = {"accession_number": f.accession_number, "form": f.form_type,
           "filed_date": f.filing_date.isoformat(), "source_url": f.source_url}  # fmt: skip
    if why:
        out["why"] = why
    return out


def _deadlines(db: Session, c: Company, start: date, end: date, today: date) -> list[dict]:
    cat = category(c.filer_category)
    reports = list(db.scalars(select(Filing).where(
        Filing.cik == c.cik, Filing.form_type.in_(ANNUAL + QUARTERLY + ("20-F",)),
        Filing.report_date.is_not(None),
        Filing.report_date >= start - timedelta(days=500),  # last year's annual report too
    ).order_by(Filing.report_date)))  # fmt: skip
    if not reports:
        return []
    is_20f = reports[-1].form_type == "20-F"
    if cat is None and not is_20f:
        return []  # a doubtful deadline is worse than none
    k_days, q_days, rule = DAYS.get(cat or "other")
    by_period: dict[date, Filing] = {}
    for f in reports:
        if not f.form_type.endswith("/A"):
            by_period.setdefault(f.report_date, f)
    latest = max(by_period) if by_period else reports[-1].report_date
    annual_md = None
    for p, f in sorted(by_period.items(), reverse=True):
        if f.form_type in ANNUAL + ("20-F",):
            annual_md = (p.month, p.day)
            break

    def is_annual(p: date) -> bool:
        if annual_md is None:
            return False
        a = date(p.year, *annual_md) if annual_md != (2, 29) else date(p.year, 2, 28)
        return abs((p - a).days) <= 10 or abs((p - a.replace(year=p.year - 1)).days) <= 10

    def due(p: date, annual: bool) -> tuple[date, str]:
        if is_20f:
            d = _add_months(p, 4)
            return next_business_day(d), ("20-F: four months after the fiscal year end "
                                          "(Form 20-F, General Instruction A)")  # fmt: skip
        n = k_days if annual else q_days
        form = "10-K" if annual else "10-Q"
        return next_business_day(p + timedelta(days=n)), (
            f"{rule}: {n} days after the {'fiscal year' if annual else 'quarter'} end "
            f"(Form {form}, General Instruction A)")  # fmt: skip

    periods = dict(by_period)
    # project forward from the latest period: quarters, or years for 20-F filers
    step = 12 if is_20f else 3
    p = latest
    while True:
        p = _add_months(p, step)
        if p > end:
            break
        periods.setdefault(p, None)
    out = []
    anchor = by_period.get(latest) or reports[-1]
    for p, f in sorted(periods.items()):
        if is_20f and f is None and not is_annual(p):
            continue
        if is_20f and f is not None and f.form_type != "20-F":
            continue
        annual = is_20f or (f.form_type in ANNUAL if f is not None else is_annual(p))
        d, basis = due(p, annual)
        if not (start <= d <= end):
            continue
        form = "20-F" if is_20f else ("10-K" if annual else "10-Q")
        item = {
            "date": d.isoformat(), "kind": "filing_deadline",
            "title": f"{form} due (period ending {p.isoformat()})", "derived": True,
            "basis": basis, "period_end": p.isoformat(), "upcoming": d >= today,
            "source": _src(anchor, "filer category and fiscal year end as the SEC lists them "
                           "for this company; the report periods as filed"),
            "met_by": _src(f) if f is not None else None,
        }  # fmt: skip
        if f is not None:
            item["filed_late"] = f.filing_date > d
        out.append(item)
    return out


def _late_notices(db, c, start, end) -> list[dict]:
    rows = db.scalars(select(Filing).where(
        Filing.cik == c.cik, Filing.form_type.in_(LATE),
        Filing.filing_date >= start, Filing.filing_date <= end))  # fmt: skip
    return [{"date": f.filing_date.isoformat(), "kind": "late_notice",
             "title": f"{f.form_type.replace('/A', ' amendment')} filed (Rule 12b-25: the report "
             "will be late)", "derived": False, "source": _src(f)} for f in rows]  # fmt: skip


def _ipo(db, c, start, end) -> list[dict]:
    out = []
    for t in db.scalars(select(IpoTerms).where(IpoTerms.cik == c.cik,
                                               IpoTerms.form_type == "424B4")):  # fmt: skip
        terms = json.loads(t.terms or "{}")
        for key, kind, title in (("lockup_expiry", "lockup_expiry", "IPO lock-up ends"),
                                 ("quiet_period_end", "quiet_period_end",
                                  "Research quiet period ends")):  # fmt: skip
            v = (terms.get(key) or {}).get("value")
            if not v:
                continue
            d = date.fromisoformat(v)
            if start <= d <= end:
                basis = (f"{terms.get('lockup_days', {}).get('value')} days after the final "
                         "prospectus" if kind == "lockup_expiry" else
                         "25 days after the IPO (FINRA Rule 2241 research quiet period)")
                out.append({"date": v, "kind": kind, "title": title, "derived": True,
                            "basis": basis,
                            "source": {"accession_number": t.accession_number, "form": "424B4",
                                       "filed_date": t.filing_date.isoformat()
                                       if t.filing_date else None,
                                       "source_url": t.source_url}})  # fmt: skip
    return out


def _proposed_sales(db, c, start, end, today) -> list[dict]:
    from app.services import form144

    since = start - timedelta(days=form144.AFTER_DAYS)
    notices = form144.for_company(db, c.cik, since, None, 200)
    out = []
    for n in notices:
        if n["followed_by"] is not None:
            continue
        base = date.fromisoformat(n["notice_date"] or n["filing"]["filed_date"])
        d = base + timedelta(days=form144.AFTER_DAYS)
        if start <= d <= end:
            out.append({"date": d.isoformat(), "kind": "proposed_sale_window_end",
                        "title": f"Form 144 notice period ends ({n['person_name']}; no sale "
                        "reported so far)", "derived": True,
                        "basis": "90 days after the notice date (Rule 144(h)); shown while no "
                        "matching Form 4 sale is on file",
                        "source": n["filing"]})  # fmt: skip
    return out


def for_company(db: Session, c: Company, start: date, end: date, kinds: tuple[str, ...],
                today: date | None = None) -> list[dict]:  # fmt: skip
    today = today or date.today()
    items: list[dict] = []
    if "filing_deadline" in kinds:
        items += _deadlines(db, c, start, end, today)
    if "late_notice" in kinds:
        items += _late_notices(db, c, start, end)
    if {"lockup_expiry", "quiet_period_end"} & set(kinds):
        items += [i for i in _ipo(db, c, start, end) if i["kind"] in kinds]
    if "proposed_sale_window_end" in kinds:
        items += _proposed_sales(db, c, start, end, today)
    company = {"cik": c.cik, "name": display_name(c.legal_name, c.ticker, c.registrant_name)}
    for i in items:
        i["company"] = company
    items.sort(key=lambda i: (i["date"], i["kind"]))
    return items


def for_companies(db: Session, ciks: list[str], start: date, end: date, kinds: tuple[str, ...],
                  cap: int = WATCHLIST_CAP) -> tuple[list[dict], bool]:  # fmt: skip
    items: list[dict] = []
    for c in db.scalars(select(Company).where(Company.cik.in_(ciks))):
        items += for_company(db, c, start, end, kinds)
    items.sort(key=lambda i: (i["date"], i["company"]["cik"], i["kind"]))
    return items[:cap], len(items) > cap
