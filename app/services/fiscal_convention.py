"""S-05: each company's fiscal-year naming convention, as its own 10-K words it.

Most companies name a fiscal year by the calendar year it ends in (the end-year rule, which
`periods` applies by default). Some name it by the year it starts in: Gap's year ended
2026-01-31 is "fiscal 2025" (offset -1). The DEI fiscal year a filing tags (`fy` on each fact)
only proposes a candidate: it is wrong often enough (Mentor Graphics tags 2016 for the year its
10-K calls "fiscal year 2017") that it never sets a label alone. The company's latest annual
report decides, where it states the mapping for the year it reports in words ("fiscal 2025 ...
ended February 1, 2026", "the year ended January 27, 2017 ("fiscal 2016")"). The offset applies
to every year, as that report names its prior years too. No readable wording: no offset (null,
the end-year rule).
"""

from __future__ import annotations

import html
import re
from collections import Counter
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import Company, FinancialFact
from app.services import periods

ANNUAL_FORMS = ("10-K", "10-K/A", "20-F", "20-F/A", "40-F", "40-F/A", "10-KT")
MIN_SHARE = 2 / 3  # of the wording's stated mappings that must agree
OFFSETS = (-1, 0, 1)

_MONTHS = ("january|february|march|april|may|june|july|august|september|october|november|"
           "december")  # fmt: skip
_MONTH_NO = {m: i + 1 for i, m in enumerate(_MONTHS.split("|"))}


def _date(name: str) -> str:
    """A date, the day optional ("March 28, 2026", "March 2026"): groups <name>m, d, y."""
    return rf"(?P<{name}m>{_MONTHS})\.?(?: (?P<{name}d>\d{{1,2}}),?)? (?P<{name}y>(?:19|20)\d\d)"


_FY = r"\bfiscal(?: year)? (?P<fy>(?:19|20)\d\d)\b"
_END = r"\b(?:ended|ending|ends|end)(?: on)?"
# a date followed by another is a list ("fiscal 2025 and fiscal 2024, which ended January 31,
# 2026 and February 1, 2025"): which name goes with which date is not said
_NOT_A_LIST = rf"(?!,? (?:and )?(?:{_MONTHS}))"


def _overlapping(pattern: str) -> re.Pattern:
    """Matches that may overlap: a rejected one ('"fiscal year 2026" or "fiscal 2026" refer to
    the period from ...') must not swallow the valid one inside it."""
    return re.compile(rf"(?=(?:{pattern}))", re.I)


_PATTERNS = (
    # "fiscal 2025 ... ended February 1, 2026"; "fiscal 2018 refers to our fiscal year ended
    # March 31, 2018"; "fiscal 2020 relate to the 52 weeks ended January 30, 2021"
    _overlapping(rf"{_FY}(?P<mid>[^.;]{{0,60}}?){_END} {_date('e')}{_NOT_A_LIST}"),
    # "fiscal 2017 began on January 30, 2016 and ended January 27, 2017"; "Fiscal 2026 ... ran
    # from March 30, 2025 through March 28, 2026"
    _overlapping(rf"{_FY}(?P<mid>[^.;]{{0,80}}?)\b(?:from|began|beginning|commenced)(?: on)? "
               rf"{_date('s')},? (?:through|to|and end(?:ed|ing|s)?(?: on)?) {_date('e')}"),
    # "the fiscal years ended January 28, 2017 ("Fiscal 2016")"; "the years ended March 2026
    # ("Fiscal 2026")"; "..., 2017, or fiscal 2016"
    _overlapping(rf"\b(?:years?|periods?) end(?:ed|ing)(?: on)? {_date('e')}"
               rf"(?P<back>[^.;\d]{{0,40}}?){_FY}"),
    # a list continuing the one above: "... and January 30, 2016 ("Fiscal 2015")"
    _overlapping(rf"{_date('e')}\s*\(\s*\"?\s*{_FY}"),
    # a table: "Fiscal 2025 January 31, 2026 52" (weeks)
    _overlapping(rf"{_FY}\s*:?\s*{_date('e')}\s+\(?(?:52|53)\b"),
)  # fmt: skip
# words between that make it a part of a year (a quarter's end would give a wrong mapping)
_PART_OF_YEAR = re.compile(
    r"(?i)quarter|month|half|interim|transition|thirteen|fourteen|sixteen|twelve|twenty|thirty|"
    r"three|six|nine|\b(?:1[2-7]|2[4-8]|3[6-9]|40)[- ]weeks?\b"
)
# words between that put a second period between the two ("fiscal 2025 compared to the year
# ended ...")
_SECOND_PERIOD = re.compile(
    r"(?i)\b(?:and|or|to|from|than|versus|vs|compared|prior|previous|preceding|last|through|"
    r"until|since|over|against|relative|next|while|whereas|both|each|all|respectively|"
    r"consist\w*|includ\w*|years|periods)\b"
)
_REFERS = re.compile(r"(?i)\b(?:refers?|relates?|corresponds?|references?|applies) to\b")
_BACK_WORDS = {"or", "the", "referred", "to", "as", "hereinafter", "herein", "which", "we",
               "refer", "our", "also", "is", "called", "and", "a", "being"}  # fmt: skip


def _text(doc: str) -> str:
    t = re.sub(r"(?is)<(script|style|ix:header)\b.*?</\1>", " ", doc)
    t = re.sub(r"<[^>]+>", " ", t)
    t = re.sub(r"[\xa0 -  ]", " ", html.unescape(t))
    return re.sub(r"\s+", " ", t.replace("“", '"').replace("”", '"'))


def _near_year_end(month: str, fiscal_year_end: str | None) -> bool:
    """The stated date is the company's fiscal year end (give or take a month for 52/53-week
    years), not a quarter's end."""
    if not (fiscal_year_end and len(fiscal_year_end) == 4 and fiscal_year_end.isdigit()):
        return True
    fye = int(fiscal_year_end[:2])
    return (_MONTH_NO[month.lower()] - fye) % 12 in (0, 1, 11)


def _plain(m: re.Match) -> bool:
    """Nothing between the name and the date that names another period."""
    d = m.groupdict()
    if d.get("back") is not None:  # the name given to that date: in parentheses, or ", or"
        back = d["back"].lower()
        named = "(" in back or re.fullmatch(r"\W*or\W*", back) or re.search(r"\bas\b", back)
        return bool(named) and set(re.findall(r"[a-z]+", back)) <= _BACK_WORDS
    mid = _REFERS.sub(" ", (d.get("mid") or "").replace(d["fy"], " "))
    mid = re.sub(r"(?i)\b5[23][- ]weeks?\b", " ", mid)  # "the 52 weeks ended", "52-week year"
    # no figure, table header or sentence between: "fiscal 2024: Fiscal Year Ended January 31,
    # 2026 January 25, 2025 ..." or "Fiscal 2025 We had net income of $1,305,722 for the year"
    return not (re.search(r"[\d:$]", mid) or len(re.findall(r"[a-z']+", mid, re.I)) > 8
                or _PART_OF_YEAR.search(mid) or _SECOND_PERIOD.search(mid))  # fmt: skip


def wording(doc: str, fiscal_year_end: str | None, own_end: date | None = None) -> Counter:
    """Counter(offset -> times the document states it): each explicit "fiscal YYYY" tied to
    the date its year ended, as the named year minus that date's end-year fiscal year. With
    `own_end` (the year end the filing reports), only statements naming that year count: a
    10-K may name a future year after a change of year end (Xura's December 2015 10-K: "year
    ending January 31, 2017 (or fiscal 2016)"), which says nothing about the years it reports."""
    t = _text(doc)
    out: Counter = Counter()
    for pattern in _PATTERNS:
        for m in pattern.finditer(t):
            if not _plain(m):
                continue
            ended = date(int(m.group("ey")), _MONTH_NO[m.group("em").lower()],
                         min(int(m.group("ed") or 15), 28))  # fmt: skip
            if own_end:  # naming the reported year end is the year-end check itself (a stored
                # fiscal year end can be stale after a change: 99 Cents Only's March)
                if abs((ended - own_end).days) > (10 if m.group("ed") else 31):
                    continue
            elif not _near_year_end(m.group("em"), fiscal_year_end):
                continue
            # against the end-year rule, which already puts the first days of January in the
            # year before (Soho House's year ended January 1, 2023 is fiscal 2022)
            out[int(m.group("fy")) - periods.fiscal_year(ended, fiscal_year_end)] += 1
    return out


def wording_offset(counts: Counter) -> int | None:
    """The offset the wording states, when its statements agree (two thirds or more of all of
    them, any that make no sense included) and it is a convention (-1, 0 or +1)."""
    if not counts:
        return None
    value, n = counts.most_common(1)[0]
    return value if value in OFFSETS and n / sum(counts.values()) >= MIN_SHARE else None


def filings(db: Session, ciks: list[str] | None = None) -> dict[str, list[tuple[date, int, str]]]:
    """{cik: [(year end, DEI fiscal year minus the end-year fiscal year, accession)]}, one per
    annual filing, oldest first: the income statement year it covers (net income or revenue)."""
    f = FinancialFact
    q = (select(f.cik, f.accession_number, func.max(f.period_end), func.max(f.fiscal_year))
         .where(f.form_type.in_(ANNUAL_FORMS), f.period_class == "annual",
                f.fiscal_year.is_not(None), f.metric.in_(("net_income", "revenue")))
         .group_by(f.cik, f.accession_number))  # fmt: skip
    if ciks is not None:
        q = q.where(f.cik.in_(ciks))
    rows = db.execute(q).all()
    fye = dict(db.execute(select(Company.cik, Company.fiscal_year_end)
                          .where(Company.cik.in_({r[0] for r in rows}))).all())  # fmt: skip
    out: dict[str, list] = {}
    for cik, acc, end, fy in rows:
        out.setdefault(cik, []).append((end, fy - periods.fiscal_year(end, fye.get(cik)), acc))
    for v in out.values():
        v.sort()
    return out


def candidates(by_cik: dict[str, list]) -> list[str]:
    """Companies whose DEI most often names the year otherwise than the end-year rule."""
    return sorted(c for c, rows in by_cik.items()
                  if Counter(d for _, d, _ in rows).most_common(1)[0][0] != 0)  # fmt: skip


def dei_disagrees(rows: list[tuple[date, int, str]], offset: int,
                  fiscal_year_end: str | None) -> list[int]:  # fmt: skip
    """End-year fiscal years whose filings' DEI names them otherwise than the offset: listed
    for review only. The offset applies to every year, as the latest 10-K names its prior
    years: splitting a company's history at a stray DEI tag would give two years one name."""
    by_year: dict[int, Counter] = {}
    for end, d, _ in rows:
        by_year.setdefault(periods.fiscal_year(end, fiscal_year_end), Counter())[d] += 1
    return sorted((y for y, c in by_year.items() if c.most_common(1)[0][0] != offset),
                  reverse=True)  # fmt: skip


def document_url(cik: str, accession: str, primary_document: str) -> str:
    acc = accession.replace("-", "")
    return f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc}/{primary_document.split('/')[-1]}"
