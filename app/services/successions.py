"""Successor registrants (launch plan K-05): a company that reorganises under a new holding
company files under a new CIK, and its history stays under the old one (ExxonMobil Holdings Corp,
CIK 2115436, succeeded Exxon Mobil Corp, CIK 34088, on 2026-07-01).

Detection, from filings already indexed:
- the successor files an 8-K12B or 8-K12G3 (securities registered as a successor issuer) on D;
- the predecessor, around D (3 days before to 30 after), files a Form 25 (delisting), a Form 15,
  or an 8-K under item 3.01 (listing transferred), 3.03 or 2.01;
- the two names are the same once legal-form words are removed (Corp, Inc, Holdings, Group,
  New, Old, ...), and exactly one company qualifies.

A detected pair is stored only once reviewed (app/data/successions_reviewed.csv): a holding
company reorganisation or redomicile the successor's report describes (high), or a merger whose
report names the predecessor as the accounting acquirer (accounting_predecessor, medium), each
with the sentence quoted. A merger whose accounting acquirer was another company is rejected:
its history is not the predecessor's. A doubtful link is worse than none.

Facts stay under the CIK that filed them; readers join the predecessor's rows at query time,
labelled with their own registrant CIK and filing. Point in time stays honest: before D, the
predecessor's rows were the ones filed.
"""

from __future__ import annotations

import csv
import re
from datetime import date, timedelta
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Company, Filing, RegistrantSuccession, utcnow
from app.services.sec_client import filing_index_url

SUCCESSOR_FORMS = ("8-K12B", "8-K12G3", "8-K12B/A", "8-K12G3/A")
EXIT_FORMS = ("25-NSE", "25", "15-12B", "15-12G", "15-15D")
EXIT_ITEMS = ("3.01", "3.03", "2.01")
STORED = ("effective_date", "evidence_accession", "evidence_form", "predecessor_accession",
          "predecessor_form")  # fmt: skip
REVIEWED = Path(__file__).resolve().parents[1] / "data" / "successions_reviewed.csv"


def reviewed(path: Path = REVIEWED) -> dict[tuple[str, str], dict]:
    """(predecessor_cik, successor_cik) -> the review: decision, match_method, confidence,
    quote and quote_url (for a rejection, the reason in quote)."""
    if not path.exists():
        return {}
    with open(path, newline="", encoding="utf-8") as fh:
        return {(r["predecessor_cik"], r["successor_cik"]): r for r in csv.DictReader(fh)}


BEFORE, AFTER = timedelta(days=3), timedelta(days=30)
_FORM_WORDS = {
    "CORP", "CORPORATION", "INC", "INCORPORATED", "CO", "COMPANY", "LTD", "LIMITED", "PLC", "LLC",
    "LP", "HOLDINGS", "HOLDING", "GROUP", "NEW", "OLD", "THE", "TOPCO", "PARENT", "SA", "NV",
    "AG", "SE", "DE", "MD", "NY",
}  # fmt: skip


def name_key(name: str | None) -> str:
    """'ExxonMobil Holdings Corp' and 'EXXON MOBIL CORP' -> 'EXXONMOBIL'."""
    words = re.sub(r"[^A-Z0-9 ]", " ", (name or "").upper().replace("&", " AND ")).split()
    return "".join(w for w in words if w not in _FORM_WORDS)


def _exits(db: Session, day: date) -> dict[str, Filing]:
    """CIK -> the filing that shows a registrant leaving its listing or merging around day."""
    rows = db.scalars(
        select(Filing).where(
            Filing.filing_date >= day - BEFORE,
            Filing.filing_date <= day + AFTER,
            (Filing.form_type.in_(EXIT_FORMS)) | (Filing.form_type.like("8-K%")),
        )
    ).all()
    out: dict[str, Filing] = {}
    for f in rows:
        items = set((f.items or "").split(","))
        if f.form_type in EXIT_FORMS or (f.form_type.startswith("8-K")
                                         and f.form_type not in SUCCESSOR_FORMS
                                         and items & set(EXIT_ITEMS)):  # fmt: skip
            prev = out.get(f.cik)
            if prev is None or (f.filing_date or date.max) < (prev.filing_date or date.max):
                out[f.cik] = f
    return out


def detect(db: Session, since: date | None = None) -> list[dict]:
    """Every predecessor -> successor pair the rules find (nothing stored)."""
    stmt = select(Filing).where(
        Filing.form_type.in_(SUCCESSOR_FORMS), Filing.filing_date.is_not(None)
    )
    if since:
        stmt = stmt.where(Filing.filing_date >= since)
    first: dict[str, Filing] = {}
    for f in db.scalars(stmt.order_by(Filing.filing_date)):
        first.setdefault(f.cik, f)  # the first succession filing per successor
    names = dict(db.execute(select(Company.cik, Company.legal_name)).all())
    found = []
    for succ_cik, f in first.items():
        key = name_key(names.get(succ_cik))
        if len(key) < 3:
            continue
        exits = _exits(db, f.filing_date)
        same = [(cik, e) for cik, e in exits.items()
                if cik != succ_cik and name_key(names.get(cik)) == key]  # fmt: skip
        if len(same) != 1:
            continue
        pred_cik, e = same[0]
        found.append({
            "predecessor_cik": pred_cik, "successor_cik": succ_cik,
            "effective_date": f.filing_date,
            "evidence_accession": f.accession_number, "evidence_form": f.form_type,
            "predecessor_accession": e.accession_number, "predecessor_form": e.form_type,
            "match_method": "successor_filing_name", "confidence": "high",
            "predecessor_name": names.get(pred_cik), "successor_name": names.get(succ_cik),
        })  # fmt: skip
    return found


def store(db: Session, pairs: list[dict], reviews: dict | None = None) -> dict:
    """Store the reviewed pairs ("store"); report the rejected and the not yet reviewed."""
    reviews = reviewed() if reviews is None else reviews
    out = {"stored_new": 0, "updated": 0, "rejected": 0, "not_reviewed": []}
    for p in pairs:
        r = reviews.get((p["predecessor_cik"], p["successor_cik"]))
        if r is None:
            out["not_reviewed"].append([p["predecessor_cik"], p["successor_cik"]])
            continue
        if r["decision"] != "store":
            out["rejected"] += 1
            continue
        row = db.get(RegistrantSuccession, (p["predecessor_cik"], p["successor_cik"]))
        if row is None:
            row = RegistrantSuccession(predecessor_cik=p["predecessor_cik"],
                                       successor_cik=p["successor_cik"])  # fmt: skip
            db.add(row)
            out["stored_new"] += 1
        else:
            out["updated"] += 1
        for k in STORED:
            setattr(row, k, p[k])
        row.match_method, row.confidence = r["match_method"], r["confidence"]
        row.quote, row.quote_url = r["quote"] or None, r["quote_url"] or None
        row.updated_at = utcnow()
    db.commit()
    return out


def predecessors(db: Session, cik: str, as_of: date | None = None) -> list[RegistrantSuccession]:
    """The chain of predecessors of cik, nearest first (a holdco of a holdco works)."""
    out, seen, cur = [], {cik}, cik
    while True:
        stmt = select(RegistrantSuccession).where(RegistrantSuccession.successor_cik == cur)
        if as_of:
            stmt = stmt.where(RegistrantSuccession.effective_date <= as_of)
        row = db.scalars(stmt.order_by(RegistrantSuccession.effective_date.desc())).first()
        if row is None or row.predecessor_cik in seen:
            return out
        out.append(row)
        seen.add(row.predecessor_cik)
        cur = row.predecessor_cik


def successor(db: Session, cik: str) -> RegistrantSuccession | None:
    return db.scalars(
        select(RegistrantSuccession).where(RegistrantSuccession.predecessor_cik == cik)
    ).first()


def as_dict(db: Session, r: RegistrantSuccession, side: str) -> dict:
    other = r.predecessor_cik if side == "predecessor" else r.successor_cik
    name = db.scalar(select(Company.legal_name).where(Company.cik == other))
    return {
        "cik": other,
        "name": name,
        "effective_date": r.effective_date.isoformat(),
        "evidence": {
            "form_type": r.evidence_form,
            "accession_number": r.evidence_accession,
            "source_url": filing_index_url(r.successor_cik, r.evidence_accession),
        },
        "match_method": r.match_method,
        "confidence": r.confidence,
        "quote": r.quote,
        "quote_url": r.quote_url,
    }
