"""Companies going public, read from their filings (ADR 0012).

A first-time registrant (no 10-K, 10-Q, 20-F or 40-F before its first registration) moves through
milestones, each one a filing:

  confidential  DRS        draft registration submitted confidentially (public once released)
  filed         S-1 / F-1  registration statement made public; Form 10 for a spin-off
  amended       S-1/A ...  amendments, usually with the price range
  effective     EFFECT     the SEC declared the registration effective
  listing       8-A12B/G   the class registered for exchange listing; CERT, the exchange's
                           certification
  priced        424B4      final prospectus with the offering price
  withdrawn     RW         registration withdrawn

The stage is the furthest milestone reached; a withdrawal after the last other milestone wins.
Each milestone links its filing.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Company, Filing

STAGES = ("confidential", "filed", "amended", "effective", "listing", "priced", "withdrawn")
MILESTONE_FORMS = {
    "confidential": ("DRS", "DRS/A"),
    "filed": ("S-1", "F-1", "10-12B", "10-12G"),
    "amended": ("S-1/A", "F-1/A", "S-1MEF", "F-1MEF", "10-12B/A", "10-12G/A"),
    "effective": ("EFFECT",),
    "listing": ("8-A12B", "8-A12G", "8-A12B/A", "8-A12G/A", "CERT"),
    "priced": ("424B4",),
    "withdrawn": ("RW",),
}
FORMS = tuple(f for forms in MILESTONE_FORMS.values() for f in forms)
REGISTRATION = MILESTONE_FORMS["confidential"] + MILESTONE_FORMS["filed"] + ("S-1/A", "F-1/A")
REPORTS = ("10-K", "10-Q", "20-F", "40-F")
BLANK_CHECK_SIC = "6770"  # SPACs
LOOKBACK = timedelta(days=730)  # a registration this old or older starts no IPO


def _ref(f: Filing) -> dict:
    return {"form_type": f.form_type, "accession_number": f.accession_number,
            "filing_date": f.filing_date, "source_url": f.source_url}  # fmt: skip


def companies(
    db: Session, since: date, stage: str | None = None, until: date | None = None
) -> list[dict]:
    """First-time registrants with a milestone filed since `since`, newest activity first."""
    recent = select(Filing.cik).where(Filing.form_type.in_(FORMS), Filing.filing_date >= since)
    if until:
        recent = recent.where(Filing.filing_date <= until)
    ciks = set(db.scalars(recent.distinct()))
    if not ciks:
        return []
    stmt = select(Filing).where(
        Filing.cik.in_(ciks),
        Filing.form_type.in_(FORMS + REPORTS),
        Filing.filing_date >= since - LOOKBACK,
    )
    if until:
        stmt = stmt.where(Filing.filing_date <= until)
    rows = db.scalars(stmt.order_by(Filing.filing_date, Filing.accession_number)).all()
    by_cik: dict[str, list[Filing]] = defaultdict(list)
    for f in rows:
        by_cik[f.cik].append(f)
    names = {c.cik: c for c in db.scalars(select(Company).where(Company.cik.in_(ciks)))}
    out = []
    for cik, filings in by_cik.items():
        item = _track(filings)
        if item is None or item["last_activity"] < since:
            continue
        if stage and item["stage"] != stage:
            continue
        c = names.get(cik)
        item.update(cik=cik, name=c.legal_name if c else cik, ticker=c.ticker if c else None,
                    exchange=c.exchange if c else None,
                    blank_check=bool(c and c.sic_code == BLANK_CHECK_SIC))  # fmt: skip
        out.append(item)
    out.sort(key=lambda i: (i["last_activity"], i["name"]), reverse=True)
    return out


def _track(filings: list[Filing]) -> dict | None:
    first_reg = next((f for f in filings if f.form_type in REGISTRATION), None)
    if first_reg is None:
        return None
    if any(f.form_type in REPORTS and f.filing_date < first_reg.filing_date for f in filings):
        return None  # already reporting before it registered: not going public
    kind = "spin_off" if first_reg.form_type.startswith("10-12") else "ipo"
    milestones: dict[str, dict] = {}
    for f in filings:
        if f.filing_date < first_reg.filing_date:
            continue
        for name, forms in MILESTONE_FORMS.items():
            if f.form_type in forms:
                # the first filing of each milestone, but the latest amendment
                if name not in milestones or name == "amended":
                    milestones[name] = _ref(f)
    if not milestones:
        return None
    reached = [s for s in STAGES if s in milestones]
    stage = reached[-1]
    if stage == "withdrawn":
        others = [milestones[s]["filing_date"] for s in reached if s != "withdrawn"]
        if others and max(others) > milestones["withdrawn"]["filing_date"]:
            stage = [s for s in reached if s != "withdrawn"][-1]  # refiled after withdrawing
    last = max(m["filing_date"] for m in milestones.values())
    return {"kind": kind, "stage": stage, "last_activity": last, "milestones": milestones}
