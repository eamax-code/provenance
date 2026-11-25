"""M-01: one filing reporting two figures for the same metric and period.

The cause: an IFRS filer whose annual report also tags US GAAP elements in its parent-only
schedules, so company facts carry the consolidated figure (ifrs-full) and the parent company's
(us-gaap) under the same tag name and period (Banco Santander Chile's 2019 liabilities, CLP 47.1
trillion consolidated and 8.39 trillion parent-only, in one 20-F). The figure the company's other
filings agree with for that period is kept; the others are ambiguous_mapping. When none agrees,
all are, and the statements show no figure for that cell, with a note. Majority, never magnitude.
"""

from __future__ import annotations

from collections import defaultdict

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.db.models import FinancialFact

SHOWN = ("ok", "partial")
STATUSES = (*SHOWN, "ambiguous_mapping")
AGREE = 0.005  # within half a percent
NOTE = ("This filing reports two different figures for this period, one tagged under IFRS and "
        "one under US GAAP, and the company's other filings agree with neither, so no figure is "
        "shown.")  # fmt: skip


def _agrees(a: float, b: float) -> bool:
    return a == b or (b != 0 and abs(a / b - 1) <= AGREE)


def find(db: Session, ciks: list[str] | None = None, statuses: tuple = SHOWN) -> list[dict]:
    """[{cik, metric, unit, period_start, period_end, accession_number, keep, drop, none}]: each
    filing that reports two or more figures for one metric and period under two taxonomies,
    among figures of these statuses (SHOWN to mark them; STATUSES to find, once marked, the
    cells none of whose figures is backed)."""
    f = FinancialFact
    q = select(f.id, f.cik, f.metric, f.unit, f.period_start, f.period_end, f.accession_number,
               f.value, f.source_taxonomy, f.quality_status).where(
        f.derived.is_(False), f.value.is_not(None), f.quality_status.in_(statuses),
        f.accession_number.is_not(None))  # fmt: skip
    if ciks:
        q = q.where(f.cik.in_(ciks))
    by_period: dict[tuple, list] = defaultdict(list)
    for r in db.execute(q):
        by_period[(r.cik, r.metric, r.unit, r.period_start, r.period_end)].append(r)
    out = []
    for key, rows in by_period.items():
        by_acc: dict[str, list] = defaultdict(list)
        for r in rows:
            by_acc[r.accession_number].append(r)
        for acc, group in by_acc.items():
            values = {float(r.value) for r in group}
            if len(values) < 2 or len({r.source_taxonomy for r in group}) < 2:
                continue
            others = [float(r.value) for r in rows
                      if r.accession_number != acc and r.quality_status in SHOWN]  # fmt: skip
            backed = [v for v in values if any(_agrees(v, o) for o in others)]
            keep = backed[0] if len(backed) == 1 else None
            out.append({"cik": key[0], "metric": key[1], "unit": key[2],
                        "period_start": key[3], "period_end": key[4], "accession_number": acc,
                        "keep": keep, "none": keep is None,
                        "drop": [r.id for r in group if keep is None
                                 or not _agrees(float(r.value), keep)],
                        "was": {r.id: r.quality_status for r in group}})  # fmt: skip
    return out


def apply(db: Session, ciks: list[str] | None = None, found: list[dict] | None = None) -> int:
    """Mark each conflicting figure that the other filings do not back. Returns how many
    changed."""
    ids = sorted({i for c in (find(db, ciks) if found is None else found) for i in c["drop"]
                  if c["was"][i] in SHOWN})  # fmt: skip
    for k in range(0, len(ids), 1000):
        db.execute(update(FinancialFact).where(FinancialFact.id.in_(ids[k:k + 1000]))
                   .values(quality_status="ambiguous_mapping"))  # fmt: skip
    return len(ids)
