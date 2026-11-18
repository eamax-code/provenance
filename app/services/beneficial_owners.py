"""Holders of more than 5% of a class, from Schedules 13D and 13G (GH #24, ADR 0011).

Since December 2024 both schedules are filed as structured XML (EDGAR form types "SCHEDULE 13D",
"SCHEDULE 13G" and their amendments), with each reporting person's name, shares and percent of
the class. Older free-text schedules ("SC 13D", "SC 13G") are not read. A holder's latest
filing is its current stake; a stake reported below 5% means the holder has dropped under the
reporting threshold.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from decimal import Decimal
from xml.etree import ElementTree

from sqlalchemy import delete, insert, select
from sqlalchemy.orm import Session

from app.db.models import BeneficialOwner, Filing, GraphSourceState, utcnow
from app.services.insiders import _find, _local, _num, safe_xml
from app.services.sec_client import SecClient, SecClientError, normalize_cik

logger = logging.getLogger("app.beneficial_owners")

XML_FORMS = ("SCHEDULE 13D", "SCHEDULE 13D/A", "SCHEDULE 13G", "SCHEDULE 13G/A")
THRESHOLD = Decimal(5)
LOOKBACK_DAYS = 3 * 365
HOLDER_TYPES = {
    "IA": "investment adviser",
    "BD": "broker-dealer",
    "BK": "bank",
    "IC": "insurance company",
    "IV": "investment company",
    "EP": "employee benefit plan",
    "HC": "parent holding company",
    "SA": "savings association",
    "CP": "church plan",
    "CO": "corporation",
    "PN": "partnership",
    "IN": "individual",
    "FI": "non-US institution",
    "OO": "other",
}


def _mdy(value: str | None) -> date | None:
    for fmt in ("%m/%d/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime((value or "").strip(), fmt).date()
        except ValueError:
            continue
    return None


def parse_schedule_xml(text: str) -> dict:
    """{filer_cik, issuer_cik, event_date, persons: [{name, cik, type, shares, percent}]}"""
    root = safe_xml(text)
    persons = []
    for node in root.iter():
        kids = {_local(c.tag) for c in node}
        if "reportingPersonName" not in kids:
            continue
        cik = _find(node, "reportingPersonCIK") or ""
        persons.append(
            {
                "name": " ".join((_find(node, "reportingPersonName") or "").split())[:200],
                "cik": normalize_cik(cik) if cik.isdigit() and int(cik) else None,
                "type": (_find(node, "typeOfReportingPerson") or "").strip()[:20] or None,
                "shares": _num(
                    _find(node, "aggregateAmountOwned")
                    or _find(node, "reportingPersonBeneficiallyOwnedAggregateNumberOfShares")
                ),
                "percent": _num(_find(node, "percentOfClass") or _find(node, "classPercent")),
            }
        )
    filer = None
    for n in root.iter():
        if _local(n.tag) == "filerCredentials":
            filer = _find(n, "cik")
            break
    issuer = None
    for tag in ("issuerCik", "issuerCIK"):
        issuer = issuer or next(
            ((n.text or "").strip() for n in root.iter() if _local(n.tag) == tag), None
        )
    event = None
    for n in root.iter():
        if _local(n.tag) in ("dateOfEvent", "eventDateRequiresFilingThisStatement"):
            event = _mdy(n.text)
            break
    return {
        "filer_cik": normalize_cik(filer) if filer and filer.isdigit() else None,
        "issuer_cik": normalize_cik(issuer) if issuer and issuer.isdigit() else None,
        "event_date": event,
        # the signature block repeats each name without a stake: those entries are dropped
        "persons": [
            p
            for p in persons
            if p["name"] and (p["shares"] is not None or p["percent"] is not None)
        ],  # fmt: skip
    }


def _doc_url(f: Filing) -> str | None:
    doc = (f.primary_document or "").split("/")[-1]
    if not doc.lower().endswith(".xml"):
        return None
    return f.source_url.rsplit("/", 1)[0] + "/" + doc


def refresh(db: Session, client: SecClient, cik: str, limit: int = 60) -> dict:
    """Read the structured 13D and 13G filings about `cik` from the last three years."""
    cik = normalize_cik(cik)
    since = date.today() - timedelta(days=LOOKBACK_DAYS)
    have = select(BeneficialOwner.accession_number).where(BeneficialOwner.subject_cik == cik)
    st = db.get(GraphSourceState, (cik, "holders"))
    skip = set((st.detail or "").split(",")) if st and st.detail else set()
    todo = db.scalars(
        select(Filing)
        .where(Filing.cik == cik, Filing.form_type.in_(XML_FORMS), Filing.filing_date >= since)
        .where(Filing.accession_number.not_in(have))
        .order_by(Filing.filing_date.desc())
        .limit(limit + len(skip))
    ).all()
    read = failed = 0
    for f in todo:
        if f.accession_number in skip or read >= limit:
            continue
        url = _doc_url(f)
        if url is None or f.filing_date is None:
            skip.add(f.accession_number)
            continue
        try:
            parsed = parse_schedule_xml(client.get_text(url).data)
        except (SecClientError, ValueError, ElementTree.ParseError):
            failed += 1
            continue
        if parsed["issuer_cik"] not in (None, cik) or not parsed["persons"]:
            skip.add(f.accession_number)
            continue
        db.execute(
            delete(BeneficialOwner).where(
                BeneficialOwner.subject_cik == cik,
                BeneficialOwner.accession_number == f.accession_number,
            )
        )
        db.execute(
            insert(BeneficialOwner),
            [
                {
                    "subject_cik": cik,
                    "accession_number": f.accession_number,
                    "form_type": f.form_type,
                    "filing_date": f.filing_date,
                    "event_date": parsed["event_date"],
                    "filer_cik": parsed["filer_cik"],
                    "position": i,
                    "holder_name": p["name"],
                    "holder_cik": p["cik"],
                    "holder_type": p["type"],
                    "shares": p["shares"],
                    "percent": p["percent"],
                    "source_url": f.source_url,
                }
                for i, p in enumerate(parsed["persons"])
            ],
        )
        read += 1
    if st is None:
        st = GraphSourceState(cik=cik, kind="holders", status="ok")
        db.add(st)
    st.detail = ",".join(sorted(skip)[-200:]) or None
    st.status = "failed" if failed and not read else "ok"
    st.checked_at = utcnow()
    db.commit()
    return {"cik": cik, "read": read, "failed": failed}


def holders(db: Session, cik: str, as_of: date | None = None, below: bool = False) -> list[dict]:
    """Each filer's latest schedule about `cik` (by `as_of`), largest stake first. The holder is
    the reporting person whose CIK is the filer's, else the one with the largest stake; the
    others on the same schedule are listed as its group."""
    cik = normalize_cik(cik)
    stmt = select(BeneficialOwner).where(BeneficialOwner.subject_cik == cik)
    if as_of:
        stmt = stmt.where(BeneficialOwner.filing_date <= as_of)
    by_acc: dict[str, list[BeneficialOwner]] = {}
    for r in db.scalars(stmt.order_by(BeneficialOwner.filing_date, BeneficialOwner.position)):
        by_acc.setdefault(r.accession_number, []).append(r)
    latest: dict[str, list[BeneficialOwner]] = {}
    for rows in by_acc.values():  # filing date order: later filings replace earlier ones
        main = _main(rows)
        key = rows[0].filer_cik or main.holder_cik or main.holder_name.lower()
        latest[key] = rows
    out = []
    for rows in latest.values():
        main = _main(rows)
        pct = max((r.percent for r in rows if r.percent is not None), default=None)
        if pct is not None and pct < THRESHOLD and not below:
            continue
        out.append(
            {
                "name": main.holder_name,
                "cik": main.holder_cik or rows[0].filer_cik,
                "holder_type": main.holder_type,
                "holder_type_label": HOLDER_TYPES.get((main.holder_type or "").split(",")[0]),
                "percent": float(pct) if pct is not None else None,
                "shares": float(main.shares) if main.shares is not None else None,
                "below_threshold": pct is not None and pct < THRESHOLD,
                "form_type": rows[0].form_type,
                "schedule": "13D" if "13D" in rows[0].form_type else "13G",
                "filing_date": rows[0].filing_date,
                "event_date": rows[0].event_date,
                "accession_number": rows[0].accession_number,
                "source_url": rows[0].source_url,
                "group": [r.holder_name for r in rows if r is not main],
            }
        )
    out.sort(key=lambda h: -(h["percent"] or 0))
    return out


def _main(rows: list[BeneficialOwner]) -> BeneficialOwner:
    filer = rows[0].filer_cik
    for r in rows:
        if filer and r.holder_cik == filer:
            return r
    return max(rows, key=lambda r: (r.percent or 0, -r.position))
