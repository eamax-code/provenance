"""When a figure was first reported (launch plan E-2).

Companies announce results in an earnings release (exhibit 99.1 to an 8-K under item 2.02)
days or weeks before the 10-Q or 10-K. A figure counts as first reported in a release only when
the release states the same value, and only for the period its 10-Q or 10-K covers (a later
filing's comparative was already known from the original filing):

- at a precision the release uses: dollars, thousands or millions, rounded, with commas
  (losses in parentheses); "$94.93 billion" in the text; per-share amounts to the cent;
- with at least four digits as printed (a per-share amount excepted), so a stray small number
  never matches;
- on a line labelled for the metric (the row label of a table line, else the line itself).

The release checked first is the earliest one filed after the period ended and no later than the
filing that reported the figure; the first that states it is recorded with the matched line as
evidence. Nothing is inferred from a release that does not state the value.
"""

from __future__ import annotations

import re
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import FinancialFact, FirstReported, utcnow
from app.services import releases
from app.services.releases import EARNINGS_ITEM

LABELS = {
    "revenue": (r"revenue|net sales|total sales|\bsales\b", r"cost of|deferred|unearned|per share"),
    "gross_profit": (r"gross (?:profit|margin)", r"%|percent"),
    "operating_income": (
        r"operating (?:income|loss|profit)|(?:income|loss) from operations", r"per share|%"
    ),
    "net_income": (r"net (?:income|earnings|loss)", r"per share|%|margin"),
    "eps_diluted": (r"diluted", r"weighted|shares used|shares outstanding"),
    "eps_basic": (r"basic", r"weighted|shares used|shares outstanding"),
    "operating_cash_flow": (
        r"operating activities|cash (?:provided |generated )?(?:by|from) operations",
        r"used in investing|financing",
    ),
    "total_assets": (r"total assets", r""),
    "cash_and_equivalents": (r"cash and cash equivalents", r"restricted|beginning"),
    "stockholders_equity": (r"(?:stockholders|shareholders)['’]? equity", r"liabilities and"),
}  # fmt: skip
PER_SHARE = {"eps_basic", "eps_diluted"}
FORMS = ("10-Q", "10-K", "10-Q/A", "10-K/A")
MIN_DIGITS = 4
# without the filing's report period: the period's own report is filed within 40-90 days
ORIGINAL_WITHIN_DAYS = 130
SCALES = ((Decimal(1), "dollars"), (Decimal(1000), "thousands"), (Decimal(10**6), "millions"))
NOTE = (
    "first_reported: the 8-K item 2.02 earnings release that stated this value before the "
    "10-Q or 10-K, with the line it was stated on; with as_of the figure counts from that date."
)


def renderings(value: Decimal, metric: str) -> list[tuple[str, str]]:
    """(regex, stated_as) for each way a release may print the value."""
    v = abs(Decimal(value))
    if v == 0:
        return []
    if metric in PER_SHARE:
        cents = v.quantize(Decimal("0.01"), ROUND_HALF_UP)
        return [] if cents != v else [(re.escape(f"{cents:.2f}"), "per share")]
    out = []
    for scale, label in SCALES:
        whole = (v / scale).quantize(Decimal(1), ROUND_HALF_UP)
        if len(str(int(whole))) >= MIN_DIGITS:
            out.append((re.escape(f"{int(whole):,}"), label))
        tenth = (v / scale).quantize(Decimal("0.1"), ROUND_HALF_UP)
        if scale > 1 and len(str(int(tenth))) >= MIN_DIGITS - 1 and tenth != whole:
            out.append((re.escape(f"{tenth:,.1f}"), label))
    if v >= 10**9:
        b = (v / Decimal(10**9)).quantize(Decimal("0.01"), ROUND_HALF_UP)
        if b >= 10:  # four digits as printed (12.34), never "1.2 billion"
            out.append((re.escape(f"{b:.2f}") + r"\s*billion", "billions"))
    return out


def _token(pattern: str) -> re.Pattern:
    return re.compile(rf"(?<![\d.,]){pattern}(?![\d]|[.,]\d)", re.I)


NARRATIVE_WINDOW = 80


def _label_part(line: str, start: int) -> str:
    """A table line's row label (its first cell), or the words just before the number."""
    if " | " in line:
        return line.split(" | ", 1)[0]
    return line[max(0, start - NARRATIVE_WINDOW) : start]


def _excerpt(line: str, start: int) -> str:
    """The line, or for a long one the words around the number: the window is cut on the line
    as matched, before spaces are collapsed (collapsing first moved the window off the number)."""
    if len(" ".join(line.split())) <= 300:
        return " ".join(line.split())
    head = " ".join(line[: line.find(" | ")].split())[:60] if " | " in line else ""
    window = " ".join(line[max(0, start - 120) : start + 120].split())
    return f"{head} … {window}" if head and not window.startswith(head) else window


def stated(text: str, metric: str, value: Decimal) -> tuple[str, str] | None:
    """(stated_as, line) when the release states the value on a line labelled for the metric."""
    if metric not in LABELS or value is None:
        return None
    want, avoid = (re.compile(p, re.I) if p else None for p in LABELS[metric])
    for pattern, label in renderings(value, metric):
        tok = _token(pattern)
        for line in text.splitlines():
            m = tok.search(line)
            if not m:
                continue
            head = _label_part(line, m.start())
            if want.search(head) and not (avoid and avoid.search(head)):
                return label, _excerpt(line, m.start())
    return None


def original(fact: FinancialFact, report_date: date | None) -> bool:
    """The figure is for the period its filing covers, not a comparative: the filing's report
    period when known, else filed within ORIGINAL_WITHIN_DAYS of the period end."""
    if report_date is not None:
        return fact.period_end == report_date
    return (fact.filed_date - fact.period_end).days <= ORIGINAL_WITHIN_DAYS


def candidates(db: Session, cik: str, since: date | None = None) -> list[FinancialFact]:
    stmt = select(FinancialFact).where(
        FinancialFact.cik == cik,
        FinancialFact.metric.in_(list(LABELS)),
        FinancialFact.derived.is_(False),
        FinancialFact.period_class.in_(["quarterly", "annual"]),
        FinancialFact.form_type.in_(FORMS),
        FinancialFact.quality_status.in_(["ok", "partial"]),
        FinancialFact.filed_date.is_not(None),
        FinancialFact.value.is_not(None),
    )
    if since:
        stmt = stmt.where(FinancialFact.period_end >= since)
    return list(db.scalars(stmt))


def match_company(db: Session, cik: str, since: date | None = None) -> int:
    """Record first-reported releases for a company's figures from the releases already stored
    (releases.ensure_read fetches them). Returns the number of figures matched."""
    from app.db.models import Filing

    rel = db.scalars(
        select(Filing)
        .where(Filing.cik == cik, Filing.form_type.like("8-K%"),
               Filing.items.like(f"%{EARNINGS_ITEM}%"))
        .order_by(Filing.filing_date, Filing.accession_number)
    ).all()  # fmt: skip
    texts = []
    for f in rel:
        row = releases.stored(db, f.accession_number)
        if row is not None and row.status == "ok" and row.text and f.filing_date:
            texts.append((f, row))
    if not texts:
        return 0
    covers = dict(db.execute(select(Filing.accession_number, Filing.report_date)
                             .where(Filing.cik == cik)).all())  # fmt: skip
    have = {
        (r.metric, r.unit, r.period_start, r.period_end, r.fact_accession)
        for r in db.scalars(select(FirstReported).where(FirstReported.cik == cik))
    }
    n = 0
    for fact in candidates(db, cik, since):
        key = (fact.metric, fact.unit, fact.period_start, fact.period_end, fact.accession_number)
        if key in have or not original(fact, covers.get(fact.accession_number)):
            continue
        for f, row in texts:
            if not (fact.period_end < f.filing_date <= fact.filed_date):
                continue
            found = stated(row.text, fact.metric, fact.value)
            if found:
                db.add(FirstReported(
                    cik=cik, metric=fact.metric, unit=fact.unit, period_start=fact.period_start,
                    period_end=fact.period_end, value=fact.value,
                    fact_accession=fact.accession_number, release_accession=f.accession_number,
                    release_filing_date=f.filing_date, release_url=row.source_url,
                    stated_as=found[0], evidence=found[1], created_at=utcnow(),
                ))  # fmt: skip
                have.add(key)
                n += 1
                break
    db.commit()
    return n


def lookup(db: Session, cik: str, accessions: set[str]) -> dict[tuple, FirstReported]:
    """{(accession, metric, unit, period_start, period_end): row} for the given filings."""
    if not accessions:
        return {}
    rows = db.scalars(
        select(FirstReported).where(
            FirstReported.cik == cik, FirstReported.fact_accession.in_(list(accessions))
        )
    )
    return {(r.fact_accession, r.metric, r.unit, r.period_start, r.period_end): r for r in rows}


def as_dict(r: FirstReported) -> dict:
    return {
        "filing_date": r.release_filing_date.isoformat(),
        "form_type": "8-K",
        "accession_number": r.release_accession,
        "source_url": r.release_url,
        "stated_as": r.stated_as,
        "evidence": r.evidence,
    }


def match_rates(db: Session) -> dict[str, tuple[int, int]]:
    """{metric: (matched, eligible)} over companies with stored releases. Eligible: a figure from
    the period's own 10-Q or 10-K with at least one stored release filed after the period ended
    and by the filing date."""
    from app.db.models import Filing, FilingSection

    ciks = set(db.scalars(
        select(Filing.cik).join(FilingSection, FilingSection.accession_number
                                == Filing.accession_number)
        .where(FilingSection.item == releases.ITEM, FilingSection.status == "ok")
    ))  # fmt: skip
    out: dict[str, list[int]] = {}
    for cik in ciks:
        rel = [f.filing_date for f in db.scalars(
            select(Filing).join(FilingSection, FilingSection.accession_number
                                == Filing.accession_number)
            .where(Filing.cik == cik, FilingSection.item == releases.ITEM,
                   FilingSection.status == "ok"))
            if f.filing_date]  # fmt: skip
        covers = dict(db.execute(select(Filing.accession_number, Filing.report_date)
                                 .where(Filing.cik == cik)).all())  # fmt: skip
        mine = db.scalars(select(FirstReported).where(FirstReported.cik == cik))
        have = {(r.metric, r.unit, r.period_start, r.period_end, r.fact_accession) for r in mine}
        for f in candidates(db, cik):
            if not original(f, covers.get(f.accession_number)):
                continue
            if not any(f.period_end < d <= f.filed_date for d in rel):
                continue
            m = out.setdefault(f.metric, [0, 0])
            m[1] += 1
            m[0] += (f.metric, f.unit, f.period_start, f.period_end, f.accession_number) in have
    return {k: (v[0], v[1]) for k, v in sorted(out.items())}
