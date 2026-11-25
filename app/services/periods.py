"""Fiscal labels for reported periods: the one place that decides what "FY2025" or "Q2 FY2026" means
(issue #3). A period is named from its end date and the company's fiscal year end (MMDD):

- a fiscal year is named by the calendar year it ends in, except that a 52/53-week year ending in
  the first week of January belongs to the year before (Advance Auto Parts' year ending
  2022-01-01 is fiscal 2021, its next one ending 2022-12-31 is fiscal 2022);
- a quarter belongs to the fiscal year that contains it (Apple's quarter ending December 2025 is
  Q1 of fiscal 2026) and is numbered from the fiscal year's start;
- S-05 (2026-11-25): then the company's own convention, as its latest 10-K words it (`offset`,
  Company.fiscal_year_offset): Gap, Target and Home Depot name a year ending in January by the
  calendar year it starts in, so their offset is -1 (Gap's year ended 2026-01-31 is FY2025). A
  company whose wording could not be read keeps the end-year rule;
- S-07 (2026-11-25): a fiscal year (annual period) is named by its own end date, and a quarter by
  the company's own fiscal year end that contains it (Company.fiscal_year_ends, the year each
  annual report covers), so a company that changed its year end, or whose stored year end is out
  of date, does not read a year ahead (Greif's year ended 2019-10-31 is FY2019, not FY2020). The
  stored fiscal year end is used only where no own year end contains the period.
"""

from __future__ import annotations

from datetime import date, timedelta

EARLY_JANUARY_DAYS = 7


Convention = tuple  # (fiscal year end MMDD or None, offset or None, own year ends or ())
YEAR_SPAN_DAYS = 372  # a 53-week year and a few days


def parse_year_ends(text: str | None) -> tuple[date, ...]:
    """Company.fiscal_year_ends ("2023-10-31,2024-10-31") -> dates, oldest first."""
    out = []
    for part in (text or "").split(","):
        try:
            out.append(date.fromisoformat(part.strip()))
        except ValueError:
            continue
    return tuple(sorted(out))


def convention(company=None, fiscal_year_end: str | None = None, offset: int | None = None,
               year_ends: tuple = ()) -> Convention:  # fmt: skip
    """A company's naming convention, (fiscal year end MMDD, offset, own year ends), to pass
    wherever a fiscal year end is expected (S-05, S-07): the functions below accept either form."""
    if company is not None:
        return (company.fiscal_year_end, company.fiscal_year_offset,
                parse_year_ends(getattr(company, "fiscal_year_ends", None)))  # fmt: skip
    return fiscal_year_end, offset, tuple(year_ends)


def _split(fiscal_year_end, offset: int | None) -> tuple[str | None, int, tuple]:
    if isinstance(fiscal_year_end, tuple):
        fye, off, ends = (tuple(fiscal_year_end) + (None, ()))[:3]
        return fye, (offset if offset else (off or 0)), tuple(ends or ())
    return fiscal_year_end, offset or 0, ()


def _in_force(period_end: date, fiscal_year_end: str | None, ends: tuple,
              period_class: str | None) -> str | None:  # fmt: skip
    """The fiscal year end (MMDD) a period is named by: a fiscal year's own end date; else the
    company's own year end containing the period (the first on or after it, within a year);
    else the stored fiscal year end."""
    if period_class == "annual":
        return f"{period_end:%m%d}"
    for e in ends:
        if e >= period_end - timedelta(days=EARLY_JANUARY_DAYS):
            return f"{e:%m%d}" if (e - period_end).days <= YEAR_SPAN_DAYS else fiscal_year_end
    return fiscal_year_end


def _fye_month(fiscal_year_end: str | None) -> int:
    if fiscal_year_end and len(fiscal_year_end) == 4 and fiscal_year_end.isdigit():
        month, day = int(fiscal_year_end[:2]), int(fiscal_year_end[2:])
        # "0102": a 52/53-week year that ends near December 31, sometimes in early January.
        if month == 1 and day <= EARLY_JANUARY_DAYS:
            return 12
        if 1 <= month <= 12:
            return month
    return 12


def fiscal_year(period_end: date, fiscal_year_end: str | None = None,
                offset: int | None = 0, period_class: str | None = None) -> int:  # fmt: skip
    """The fiscal year a period ending on this date belongs to, as the company names it."""
    fiscal_year_end, offset, ends = _split(fiscal_year_end, offset)
    shifted = period_end - timedelta(days=EARLY_JANUARY_DAYS)
    fye = _fye_month(_in_force(period_end, fiscal_year_end, ends, period_class))
    # Days near the turn of the year shift back into the year they close; a quarter ending
    # after the fiscal year-end month opens the next fiscal year.
    return shifted.year + (1 if shifted.month > fye else 0) + offset


def fiscal_quarter(period_end: date, fiscal_year_end: str | None = None) -> int:
    """1 to 4: which quarter of its fiscal year a quarter ending on this date is."""
    fiscal_year_end, _, ends = _split(fiscal_year_end, 0)
    shifted = period_end - timedelta(days=EARLY_JANUARY_DAYS)
    fye = _fye_month(_in_force(period_end, fiscal_year_end, ends, "quarterly"))
    return (shifted.month - fye - 1) % 12 // 3 + 1


def label(period_end: date, period_class: str, fiscal_year_end: str | None = None,
          offset: int | None = 0) -> str:  # fmt: skip
    fy = fiscal_year(period_end, fiscal_year_end, offset, period_class)
    if period_class == "quarterly":
        return f"Q{fiscal_quarter(period_end, fiscal_year_end)} FY{fy}"
    return f"FY{fy}"


def labels(ends: list[date], period_class: str, fiscal_year_end: str | None = None,
           offset: int | None = 0) -> list[str]:  # fmt: skip
    """Labels for a series; when a change of year end makes two periods share a label, each of
    them also names the month it ended ("FY2015 (Sep)", "FY2015 (Dec)")."""
    base = [label(e, period_class, fiscal_year_end, offset) for e in ends]
    seen: dict[str, int] = {}
    for b in base:
        seen[b] = seen.get(b, 0) + 1
    out = [f"{b} ({e:%b})" if seen[b] > 1 else b for b, e in zip(base, ends, strict=True)]
    # S-07: two periods ending in the same month (one quarter stored as ending on the 30th and
    # the 31st by two filings) get their dates: a key is never shared
    again: dict[str, int] = {}
    for o in out:
        again[o] = again.get(o, 0) + 1
    return [
        f"{b} ({e.isoformat()})" if again[o] > 1 else o
        for b, o, e in zip(base, out, ends, strict=True)
    ]


def is_fiscal_year_end(end: date, year_ends: tuple, near: int = 7) -> bool:
    """S-07: an annual period ending here is a fiscal year of the company: its end falls, within
    a week, on the month and day of the company's own year end nearest in time (Broadcom's 2008,
    a comparative year in its first XBRL 10-K, ends on December 31 as its own years do; AAR's
    12-month period to November 30 does not, its own years end on May 31). True when no own
    year ends are known."""
    if not year_ends:
        return True
    o = min(year_ends, key=lambda x: abs((x - end).days))
    for y in (end.year - 1, end.year, end.year + 1):
        try:
            same = date(y, o.month, o.day)
        except ValueError:  # February 29
            same = date(y, o.month, 28)
        if abs((same - end).days) <= near:
            return True
    return False


def transition_label(start: date, end: date) -> str:
    """S-07: a short period between two fiscal years when a company changes its year end (a
    10-KT): never a fiscal year."""
    months = round((end - start).days / 30.44)
    return f"Transition period ({months} months, ended {end.isoformat()})"


def calendar_period(start: date | None, end: date, period_class: str) -> str | None:
    """The calendar period a figure belongs to, as the SEC frames it: the calendar year or
    quarter the period overlaps most (its midpoint), "CY2024" or "CY2024Q4"; a balance at a
    date is the quarter it falls in, "CY2024Q3I". None for year-to-date and other periods."""
    if start is None:  # an instant
        return f"CY{end.year}Q{(end.month - 1) // 3 + 1}I"
    mid = start + (end - start) / 2
    if period_class in ("annual", "ttm"):
        return f"CY{mid.year}"
    if period_class == "quarterly":
        return f"CY{mid.year}Q{(mid.month - 1) // 3 + 1}"
    return None


def parse_calendar_period(text: str) -> tuple[int, int | None, bool] | None:
    """("CY2025Q3I") -> (2025, 3, True); None when it is not a calendar period."""
    import re

    m = re.fullmatch(r"CY(\d{4})(?:Q([1-4]))?(I)?", text.strip().upper())
    if not m or (m.group(3) and not m.group(2)):
        return None
    return int(m.group(1)), int(m.group(2)) if m.group(2) else None, bool(m.group(3))


def label_basis(conv: Convention) -> str:
    """How a company's labels were set (S-05): its own 10-K wording, or the end-year rule."""
    return "end-year rule" if conv[1] is None else "company's 10-K wording"
