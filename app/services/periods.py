"""Fiscal labels for reported periods: the one place that decides what "FY2025" or "Q2 FY2026" means
(issue #3). A period is named from its end date and the company's fiscal year end (MMDD):

- a fiscal year is named by the calendar year it ends in, except that a 52/53-week year ending in
  the first week of January belongs to the year before (Advance Auto Parts' year ending
  2022-01-01 is fiscal 2021, its next one ending 2022-12-31 is fiscal 2022);
- a quarter belongs to the fiscal year that contains it (Apple's quarter ending December 2025 is
  Q1 of fiscal 2026) and is numbered from the fiscal year's start.
"""

from __future__ import annotations

from datetime import date, timedelta

EARLY_JANUARY_DAYS = 7


def _fye_month(fiscal_year_end: str | None) -> int:
    if fiscal_year_end and len(fiscal_year_end) == 4 and fiscal_year_end.isdigit():
        month, day = int(fiscal_year_end[:2]), int(fiscal_year_end[2:])
        # "0102": a 52/53-week year that ends near December 31, sometimes in early January.
        if month == 1 and day <= EARLY_JANUARY_DAYS:
            return 12
        if 1 <= month <= 12:
            return month
    return 12


def fiscal_year(period_end: date, fiscal_year_end: str | None = None) -> int:
    """The fiscal year a period ending on this date belongs to."""
    shifted = period_end - timedelta(days=EARLY_JANUARY_DAYS)
    fye = _fye_month(fiscal_year_end)
    # Days near the turn of the year shift back into the year they close; a quarter ending
    # after the fiscal year-end month opens the next fiscal year.
    return shifted.year + (1 if shifted.month > fye else 0)


def fiscal_quarter(period_end: date, fiscal_year_end: str | None = None) -> int:
    """1 to 4: which quarter of its fiscal year a quarter ending on this date is."""
    shifted = period_end - timedelta(days=EARLY_JANUARY_DAYS)
    fye = _fye_month(fiscal_year_end)
    return (shifted.month - fye - 1) % 12 // 3 + 1


def label(period_end: date, period_class: str, fiscal_year_end: str | None = None) -> str:
    fy = fiscal_year(period_end, fiscal_year_end)
    if period_class == "quarterly":
        return f"Q{fiscal_quarter(period_end, fiscal_year_end)} FY{fy}"
    return f"FY{fy}"


def labels(ends: list[date], period_class: str, fiscal_year_end: str | None = None) -> list[str]:
    """Labels for a series; when a change of year end makes two periods share a label, each of
    them also names the month it ended ("FY2015 (Sep)", "FY2015 (Dec)")."""
    base = [label(e, period_class, fiscal_year_end) for e in ends]
    seen: dict[str, int] = {}
    for b in base:
        seen[b] = seen.get(b, 0) + 1
    return [f"{b} ({e:%b})" if seen[b] > 1 else b for b, e in zip(base, ends, strict=True)]
