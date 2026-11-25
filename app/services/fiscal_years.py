"""S-07: a company's own fiscal years and transition periods, read from its annual reports.

- An annual report's own year is its annual period ending at the filing's period of report
  (within a week), else its latest annual period; its comparative years ending on the same
  month and day are own years too (Eros' 2020 transition report brings STX's years ended
  September 2017-2019, the accounting acquirer's).
- A transition period is an annual report's latest period when no annual period ends on that
  date and it runs 2 to 11 months, whatever the form (a 10-KT; Eros' 20-F "for the transition
  period from September 30, 2019 to March 31, 2020"), and it starts the day after an own fiscal
  year ended (within a week) and ends on the month and day of the company's next own fiscal year
  (its new year end; with no later year, only a 10-KT counts). A 10-K that also carries a later
  interim (SafeSpace's six months to January 2020 in its July 2019 10-K) is not one, nor is an
  ordinary 10-K: its latest period is its fiscal
  year, which ends on that date. Nor is a new company's first short period ("from inception"):
  no own fiscal year ended before it.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Filing, FinancialFact

FORMS = ("10-K", "10-K/A", "20-F", "20-F/A", "40-F", "40-F/A", "10-KT", "10-KT/A")
NEAR = 7
SHORT = (60, 340)  # days: 2 to 11 months


def _same_day(a: date, b: date) -> bool:
    for y in (a.year - 1, a.year, a.year + 1):
        try:
            if abs((date(y, b.month, b.day) - a).days) <= NEAR:
                return True
        except ValueError:  # February 29
            if abs((date(y, b.month, 28) - a).days) <= NEAR:
                return True
    return False


def _periods(db: Session, ciks: list[str] | None):
    """(cik, accession, form, filed, report date, period class, start, end) of each annual
    report's net income or revenue periods."""
    f = FinancialFact
    q = (select(f.cik, f.accession_number, f.form_type, f.filed_date, Filing.report_date,
                f.period_class, f.period_start, f.period_end)
         .outerjoin(Filing, Filing.accession_number == f.accession_number)
         .where(f.quality_status.in_(("ok", "partial")),
                f.metric.in_(("net_income", "revenue")), f.form_type.in_(FORMS),
                f.period_start.is_not(None))
         .distinct())  # fmt: skip
    if ciks:
        q = q.where(f.cik.in_(ciks))
    return db.execute(q).all()


def own_year_ends(db: Session, ciks: list[str] | None = None) -> dict[str, list[date]]:
    """{cik: own fiscal year ends, oldest first}"""
    by_filing: dict[tuple, list] = defaultdict(list)
    report: dict[tuple, date | None] = {}
    for cik, acc, _form, _filed, rep, cls, _start, end in _periods(db, ciks):
        if cls == "annual":
            by_filing[(cik, acc)].append(end)
            report[(cik, acc)] = rep
    out: dict[str, set] = defaultdict(set)
    for key, ends in by_filing.items():
        rep = report[key]
        near = [e for e in ends if rep and abs((e - rep).days) <= NEAR]
        own = max(near) if near else max(ends)
        out[key[0]].update(e for e in ends if _same_day(e, own))  # own year and comparatives
    result = {}
    for cik, ends in out.items():
        kept: list = []
        for e in sorted(ends):  # one per year: a 52/53-week year moves by a few days
            if kept and (e - kept[-1]).days <= NEAR:
                kept[-1] = e
            else:
                kept.append(e)
        result[cik] = kept
    return result


def transitions(db: Session, ciks: list[str] | None = None,
                as_of: date | None = None) -> dict[str, list[tuple]]:  # fmt: skip
    """{cik: [(start, end, accession, form, filed)]}: each annual report whose latest period is
    a transition period (see the module docstring); with as_of, only reports filed by then."""
    by_filing: dict[tuple, list] = defaultdict(list)
    for row in _periods(db, ciks):
        by_filing[(row[0], row[1])].append(row)
    own = own_year_ends(db, ciks)
    out: dict[str, list] = defaultdict(list)
    for (cik, acc), rows in by_filing.items():
        latest = max(r[7] for r in rows)
        at_end = [r for r in rows if abs((r[7] - latest).days) <= NEAR]
        if any(r[5] == "annual" for r in at_end):
            continue  # the report's latest period is a fiscal year
        short = [r for r in at_end if r[7] == latest and r[5] in ("other", "ytd")
                 and SHORT[0] <= (r[7] - r[6]).days <= SHORT[1]]  # fmt: skip
        if not short:
            continue
        r = max(short, key=lambda r: (r[7] - r[6]).days)  # the whole transition period
        ends = own.get(cik, ())
        if not any(0 <= (r[6] - e).days <= NEAR + 1 for e in ends):
            continue  # no fiscal year ended just before it: a first period, not a transition
        later = [e for e in ends if e >= r[7] - timedelta(days=NEAR)]  # its end or after
        if later and not _same_day(r[7], min(later)):
            continue  # the next fiscal year ends on another day: an interim after the year
        if not later and not r[2].startswith("10-KT"):
            continue  # no later fiscal year to show the new year end: only a 10-KT says so
        if as_of and r[3] and r[3] > as_of:
            continue
        out[cik].append((r[6], r[7], acc, r[2], r[3]))
    return out
