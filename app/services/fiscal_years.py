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

from sqlalchemy import distinct, func, select
from sqlalchemy.orm import Session

from app.db.models import Company, Filing, FinancialFact

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
    return _chains(db, ciks)[0]


def _chains(db: Session, ciks: list[str] | None) -> tuple[dict, dict]:
    """({cik: own year ends}, {cik: [(start, end, accession, form, filed)]} of the short periods
    a report presents between two of its fiscal years)."""
    by_filing: dict[tuple, list] = defaultdict(list)
    report: dict[tuple, tuple] = {}
    for cik, acc, form, filed, rep, cls, start, end in _periods(db, ciks):
        if cls in ("annual", "other", "ytd"):
            by_filing[(cik, acc)].append((cls, start, end))
            report[(cik, acc)] = (rep, form, filed)
    out: dict[str, set] = defaultdict(set)
    shorts: dict[str, list] = defaultdict(list)
    for key, periods in by_filing.items():
        annual = [p for p in periods if p[0] == "annual"]
        if not annual:
            continue
        rep, form, filed = report[key]
        near = [p for p in annual if rep and abs((p[2] - rep).days) <= NEAR]
        own = max(near or annual, key=lambda p: p[2])
        found = {p[2] for p in annual if _same_day(p[2], own[2])}  # own year and comparatives
        # the run of periods the report presents back from its own year, each ending the day
        # before the next starts: the 12-month ones are fiscal years, short ones transitions
        # (Cenntro's report for January 2018: a 7-month transition to January 2017, then its
        # June 2016 and 2015 years)
        cur, run, after = own, [], own
        for _ in range(12):
            prev = [p for p in periods if 0 < (cur[1] - p[2]).days <= 4 and (
                p[0] == "annual" or SHORT[0] <= (p[2] - p[1]).days <= SHORT[1])]  # fmt: skip
            if not prev:
                break
            cur = max(prev, key=lambda p: (p[2] - p[1]).days)
            if cur[0] == "annual":
                found.add(cur[2])
                # one short period between two fiscal years ending on different days: the year
                # end changed. Two short periods, or years ending on the same day either side,
                # are a predecessor's and successor's parts of one year (Frontier's four months
                # to April 2021 beside eight from May; Waldencast's to July 2022), never one
                if len(run) == 1 and not _same_day(cur[2], after[2]):
                    shorts[key[0]].append((run[0][1], run[0][2], key[1], form, filed))
                run, after = [], cur
            else:
                run.append(cur)
        out[key[0]].update(found)
    result = {}
    for cik, ends in out.items():
        kept: list = []
        for e in sorted(ends):  # one per year: a 52/53-week year moves by a few days
            if kept and (e - kept[-1]).days <= NEAR:
                kept[-1] = e
            else:
                kept.append(e)
        result[cik] = kept
    return result, shorts


def transitions(db: Session, ciks: list[str] | None = None,
                as_of: date | None = None) -> dict[str, list[tuple]]:  # fmt: skip
    """{cik: [(start, end, accession, form, filed)]}: each annual report whose latest period is
    a transition period (see the module docstring); with as_of, only reports filed by then."""
    by_filing: dict[tuple, list] = defaultdict(list)
    for row in _periods(db, ciks):
        by_filing[(row[0], row[1])].append(row)
    own, chained = _chains(db, ciks)
    out: dict[str, list] = defaultdict(list)
    for cik, spans in chained.items():  # short periods inside a report's run of years
        for span in spans:
            if not (as_of and span[4] and span[4] > as_of):
                out[cik].append(span)
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


def left_out(db: Session, ciks: list[str] | None = None) -> set[tuple]:
    """S-07b: {(cik, period type, unit, period end)} of the annual periods that are not a fiscal
    year's column, such as an adoption-date balance at January 1, 2018; the marts leave them out
    as the statements do, choosing per period type (periods.one_per_year_end): balances apart
    from durations, as the balance sheet is apart from the income statement; and per unit, so a
    company that moved to US dollars keeps its dollar opening balance beside the year end in
    its old currency (BELLUS Health's January 1, 2019 beside its Canadian dollar December 31)."""
    from app.services import periods

    f = FinancialFact
    q = (select(f.cik, f.period_type, f.unit, f.period_end, func.count(distinct(f.metric)))
         .where(f.period_class == "annual", f.derived.is_(False), f.value.is_not(None),
                f.quality_status.in_(("ok", "partial")))
         .group_by(f.cik, f.period_type, f.unit, f.period_end))  # fmt: skip
    if ciks:
        q = q.where(f.cik.in_(ciks))
    counts: dict[tuple, dict] = defaultdict(dict)
    for cik, ptype, unit, end, n in db.execute(q):
        counts[(cik, ptype, unit)][end] = n
    if not counts:
        return set()
    scope = sorted({k[0] for k in counts})
    cq = select(Company.cik, Company.fiscal_year_ends).where(Company.fiscal_year_ends.is_not(None))
    own = {c: tuple(periods.parse_year_ends(v)) for c, v in db.execute(
        cq.where(Company.cik.in_(scope)) if ciks else cq)}  # fmt: skip
    rq = select(Filing.cik, Filing.report_date).where(Filing.report_date.is_not(None),
                                                      Filing.form_type.in_(FORMS))  # fmt: skip
    reports: dict[str, set] = defaultdict(set)
    for c, r in db.execute(rq.where(Filing.cik.in_(scope)) if ciks else rq):
        reports[c].add(r)
    t_ends: dict[str, list] = {c: [x[1] for x in xs] for c, xs in transitions(db, ciks).items()}
    out = set()
    for (cik, ptype, unit), by_end in counts.items():
        if not own.get(cik):
            continue
        skip = {e for e in by_end if any(abs((e - t).days) <= NEAR for t in t_ends.get(cik, ()))}
        for e in periods.one_per_year_end(by_end, own[cik], reports.get(cik, set()), skip):
            out.add((cik, ptype, unit, e))
    return out
