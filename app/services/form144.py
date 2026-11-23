"""Form 144 notices of proposed sale (D-12, docs/contracts/insider-plans.md).

Since April 2023 a Form 144 is filed electronically with a structured XML document. Each notice
is read once through the SEC client (the Archives copy, cached) and stored as given. The Form 4
that reported the sale is joined at read time, so later Form 4s join without a reload.

Join rule: the first Form 4 by the same issuer and the same person (the notice filer's CIK,
else the normalized name: last name and first initial), filed on or after the notice, that
reports a sale (code S) dated from 7 days before to 90 days after the notice date (a notice
covers sales within three months, Rule 144(h)). No match is normal: a notice does not oblige a
sale. Information, not signals.
"""

from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import (
    DatedEvent,
    Filing,
    Form144Notice,
    InsiderFiling,
    InsiderTransaction,
    utcnow,
)
from app.services import dated_events
from app.services.sec_client import normalize_cik

PROPOSED_SALE = dated_events.PROPOSED_SALE
BEFORE_DAYS = 7
AFTER_DAYS = 90
MAX_ACQUIRED = 20
FRESH_DAYS = 1
NOTES = [
    "Proposed sales are Form 144 notices as filed (values as given in the notice; the market "
    "value is the filer's own estimate). The Form 4 shown with a notice is the first sale "
    "(code S) by the same person at the same issuer, filed on or after the notice and dated "
    f"from {BEFORE_DAYS} days before to {AFTER_DAYS} days after the notice date, matched by "
    "CIK, else by name; a notice does not oblige a sale.",
    "followed_by_status is pending while the Form 4 data for the notice's 90 days is not "
    "complete yet (the SEC's quarterly insider data sets, plus the Form 4s read as filed).",
]


def xml_url(cik: str, accession_number: str) -> str:
    """The notice's raw XML in the filing folder (the primary document is an XSL rendering)."""
    return (f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/"
            f"{accession_number.replace('-', '')}/primary_doc.xml")  # fmt: skip


def _mdy(v: str | None) -> date | None:
    try:
        return datetime.strptime((v or "").strip(), "%m/%d/%Y").date()
    except ValueError:
        return None


def _dec(v: str | None) -> float | None:
    try:
        return float((v or "").replace(",", "").strip())
    except ValueError:
        return None


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _find(el, name):
    for c in el.iter():
        if _local(c.tag) == name:
            return c
    return None


def _text(el, name) -> str | None:
    f = _find(el, name) if el is not None else None
    t = (f.text or "").strip() if f is not None else ""
    return " ".join(t.split()) or None


def _children(el, name):
    return [c for c in el.iter() if _local(c.tag) == name] if el is not None else []


def parse(xml: str) -> dict | None:
    """The notice's fields, or None when the document is not a Form 144 XML."""
    try:
        root = ET.fromstring(xml.encode("utf-8") if isinstance(xml, str) else xml)
    except ET.ParseError:
        return None
    form = _find(root, "formData")
    if form is None or _find(root, "issuerInfo") is None:
        return None
    info = _find(form, "issuerInfo")
    sec_info = _children(form, "securitiesInformation")
    shares = [_dec(_text(s, "noOfUnitsSold")) for s in sec_info]
    values = [_dec(_text(s, "aggregateMarketValue")) for s in sec_info]
    sale_dates = [d for d in (_mdy(_text(s, "approxSaleDate")) for s in sec_info) if d]
    acquired = []
    for a in _children(form, "securitiesToBeSold"):
        acquired.append({"date": (_mdy(_text(a, "acquiredDate")) or None) and
                         _mdy(_text(a, "acquiredDate")).isoformat(),
                         "nature": _text(a, "natureOfAcquisitionTransaction"),
                         "shares": _dec(_text(a, "amountOfSecuritiesAcquired"))})  # fmt: skip
    plan_dates = [d for d in (_mdy(p.text) for p in _children(form, "planAdoptionDate")) if d]
    filer = _text(_find(root, "filerCredentials"), "cik") if _find(root, "filerCredentials") is \
        not None else None  # fmt: skip
    first = sec_info[0] if sec_info else None
    return {
        "issuer_cik": normalize_cik(_text(info, "issuerCik") or "0"),
        "person_name": _text(info, "nameOfPersonForWhoseAccountTheSecuritiesAreToBeSold"),
        "person_cik": normalize_cik(filer) if filer and filer.isdigit() else None,
        "relationships": json.dumps([r.text.strip() for r in
                                     _children(info, "relationshipToIssuer") if r.text]),
        "security_class": _text(first, "securitiesClassTitle") if first is not None else None,
        "shares": sum(s for s in shares if s is not None) if any(s is not None for s in shares)
        else None,
        "aggregate_market_value": sum(v for v in values if v is not None)
        if any(v is not None for v in values) else None,
        "shares_outstanding": _dec(_text(first, "noOfUnitsOutstanding")) if first is not None
        else None,
        "approx_sale_date": min(sale_dates) if sale_dates else None,
        "exchange": _text(first, "securitiesExchangeName") if first is not None else None,
        "broker": _text(_find(first, "brokerOrMarketmakerDetails"), "name")
        if first is not None and _find(first, "brokerOrMarketmakerDetails") is not None else None,
        "acquired": json.dumps(acquired[:MAX_ACQUIRED]), "acquired_count": len(acquired),
        "plan_adoption_date": max(plan_dates) if plan_dates else None,
        "notice_date": _mdy(_text(form, "noticeDate")),
    }  # fmt: skip


# -- join -------------------------------------------------------------------------------


def name_key(name: str | None) -> str | None:
    """Last name and first initial, case and punctuation ignored. Form 4 and Form 144 both
    write 'LAST FIRST MIDDLE' most of the time; 'First Last' is tried as well by the caller."""
    words = [w for w in re.sub(r"[^A-Za-z ]", " ", name or "").upper().split()
             if w not in ("JR", "SR", "II", "III", "IV", "MR", "MS", "MRS", "DR")]  # fmt: skip
    if len(words) < 2:
        return None
    return f"{words[0]}|{words[1][0]}"


def _name_keys(name: str | None) -> set[str]:
    keys = {name_key(name)}
    words = re.sub(r"[^A-Za-z ]", " ", name or "").split()
    if len(words) >= 2:  # 'First Middle Last' -> 'Last First'
        keys.add(name_key(" ".join([words[-1]] + words[:-1])))
    return {k for k in keys if k}


def _sales(db: Session, issuer_cik: str, start: date, end: date) -> list[dict]:
    rows = db.execute(
        select(InsiderTransaction.accession_number, InsiderTransaction.trans_date,
               InsiderTransaction.shares, InsiderTransaction.price,
               InsiderTransaction.security_title,
               InsiderFiling.owner_cik, InsiderFiling.owner_name, InsiderFiling.filing_date,
               InsiderFiling.form_type)
        .join(InsiderFiling, (InsiderFiling.accession_number == InsiderTransaction.accession_number)
              & (InsiderFiling.issuer_cik == InsiderTransaction.issuer_cik))
        .where(InsiderTransaction.issuer_cik == issuer_cik,
               InsiderTransaction.trans_code == "S",
               InsiderTransaction.is_derivative.is_(False),
               InsiderTransaction.trans_date >= start, InsiderTransaction.trans_date <= end)
    ).all()  # fmt: skip
    by_acc: dict[str, dict] = {}
    for r in rows:
        s = by_acc.setdefault(r.accession_number, {
            "accession_number": r.accession_number, "owner_ciks": set(), "owner_keys": set(),
            "filing_date": r.filing_date, "form": r.form_type, "lines": []})  # fmt: skip
        s["owner_ciks"].add(normalize_cik(r.owner_cik) if r.owner_cik else None)
        s["owner_keys"] |= _name_keys(r.owner_name)
        s["lines"].append((r.trans_date, float(r.shares or 0), float(r.price or 0)))
    out = []
    for s in by_acc.values():
        lines = sorted(set(s["lines"]))
        total = sum(x[1] for x in lines)
        out.append({**s, "transaction_date": lines[0][0], "shares": total,
                    "average_price": round(sum(x[1] * x[2] for x in lines) / total, 4)
                    if total else None})  # fmt: skip
    out.sort(key=lambda s: (s["transaction_date"], s["filing_date"] or date.max,
                            s["accession_number"]))  # fmt: skip
    return out


def match(notice: Form144Notice, sales: list[dict], as_of: date | None = None) -> dict | None:
    start = notice.notice_date or notice.filing_date
    lo, hi = start - timedelta(days=BEFORE_DAYS), start + timedelta(days=AFTER_DAYS)
    keys = _name_keys(notice.person_name)
    by_cik = [s for s in sales if notice.person_cik and notice.person_cik in s["owner_ciks"]]
    rule, pool = "same_person_cik", by_cik
    if not by_cik:
        rule = "same_person_name"
        pool = [s for s in sales if keys & s["owner_keys"]]
    for s in pool:
        if not (lo <= s["transaction_date"] <= hi):
            continue
        if s["filing_date"] and s["filing_date"] < notice.filing_date:
            continue  # filed before the notice: it reports an earlier sale (hand-check 11-24)
        if as_of and s["filing_date"] and s["filing_date"] > as_of:
            continue
        return {"accession_number": s["accession_number"], "form": s["form"] or "4",
                "filed_date": s["filing_date"].isoformat() if s["filing_date"] else None,
                "transaction_date": s["transaction_date"].isoformat(), "shares": s["shares"],
                "average_price": s["average_price"],
                "match": {"rule": rule,
                          "days_after_notice": (s["transaction_date"] - start).days}}  # fmt: skip
    return None


def _num(v):
    if v is None:
        return None
    f = float(v)
    return int(f) if f.is_integer() else f


def for_company(db: Session, cik: str, since: date, as_of: date | None, limit: int) -> list[dict]:
    q = select(Form144Notice).where(Form144Notice.issuer_cik == cik,
                                    Form144Notice.filing_date >= since)  # fmt: skip
    if as_of:
        q = q.where(Form144Notice.filing_date <= as_of)
    notices = list(
        db.scalars(
            q.order_by(
                Form144Notice.filing_date.desc(), Form144Notice.accession_number.desc()
            ).limit(limit)
        )
    )
    if not notices:
        return []
    lo = min(n.notice_date or n.filing_date for n in notices) - timedelta(days=BEFORE_DAYS)
    hi = max(n.notice_date or n.filing_date for n in notices) + timedelta(days=AFTER_DAYS)
    sales = _sales(db, cik, lo, hi)
    from app.services.insiders import dataset_coverage

    covered = dataset_coverage(db)  # the quarterly Form 4 data sets reach this filing date
    f4_urls = dict(
        db.execute(
            select(Filing.accession_number, Filing.source_url).where(
                Filing.accession_number.in_({s["accession_number"] for s in sales} or {""})
            )
        ).all()
    )
    out = []
    for n in notices:
        m = match(n, sales, as_of)
        if m:
            m["source_url"] = f4_urls.get(m["accession_number"]) or (
                f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/"
                f"{m['accession_number'].replace('-', '')}/")  # fmt: skip
        out.append({
            "person_name": n.person_name, "person_cik": n.person_cik,
            "relationships": json.loads(n.relationships), "security_class": n.security_class,
            "shares": _num(n.shares), "aggregate_market_value": _num(n.aggregate_market_value),
            "shares_outstanding": _num(n.shares_outstanding),
            "approx_sale_date": n.approx_sale_date.isoformat() if n.approx_sale_date else None,
            "exchange": n.exchange, "broker": n.broker, "acquired": json.loads(n.acquired),
            "acquired_count": n.acquired_count,
            "plan_adoption_date": n.plan_adoption_date.isoformat() if n.plan_adoption_date
            else None,
            "notice_date": n.notice_date.isoformat() if n.notice_date else None,
            "filing": {"accession_number": n.accession_number, "form": n.form_type,
                       "filed_date": n.filing_date.isoformat(), "source_url": n.source_url},
            "followed_by": m,
            "followed_by_status": "matched" if m else (
                "no_sale_reported" if covered
                and (n.notice_date or n.filing_date) + timedelta(days=AFTER_DAYS) <= covered
                else "pending"),
        })  # fmt: skip
    return out


# -- load -------------------------------------------------------------------------------


def load(
    db: Session,
    client,
    since: date,
    write: bool = True,
    limit: int | None = None,
    only: list[str] | None = None,
) -> dict:
    """Read every Form 144 filed since `since` that is not stored yet (cached documents cost no
    request). With write False nothing is stored and the parsed rows are returned for review."""
    from app.services.sec_client import SecNotFound

    have = set(db.scalars(select(Form144Notice.accession_number)))
    q = select(Filing).where(Filing.form_type.in_(["144", "144/A"]), Filing.filing_date >= since)
    if only:
        q = q.where(Filing.accession_number.in_(only))
    filings, seen = [], set(have)
    for f in db.scalars(q.order_by(Filing.filing_date.desc(), Filing.cik)):
        if f.accession_number not in seen:  # a notice is listed under the issuer and the filer
            seen.add(f.accession_number)
            filings.append(f)
    filings = filings[:limit]
    stats = {"filings": len(filings), "stored": 0, "not_xml": 0, "missing": 0}
    rows = []
    for f in filings:
        try:
            doc = client.get_text(xml_url(f.cik, f.accession_number)).data
        except SecNotFound:
            stats["missing"] += 1
            continue
        parsed = parse(doc)
        if parsed is None:
            stats["not_xml"] += 1
            continue
        row = {**parsed, "accession_number": f.accession_number, "form_type": f.form_type,
               "filing_date": f.filing_date, "source_url": f.source_url}  # fmt: skip
        if parsed["issuer_cik"] in (None, "0000000000"):
            row["issuer_cik"] = f.cik
        rows.append(row)
        if write:
            db.add(Form144Notice(**row))
            stats["stored"] += 1
            if stats["stored"] % 2000 == 0:
                db.commit()
    if write:
        db.commit()
    stats["rows"] = rows if not write else None
    return stats


def emit_events(db: Session, today: date | None = None) -> list[DatedEvent]:
    today = today or date.today()
    have = set(db.scalars(select(DatedEvent.accession_number)
                          .where(DatedEvent.event_type == PROPOSED_SALE)))  # fmt: skip
    added = []
    for n in db.scalars(select(Form144Notice)):
        if n.accession_number in have:
            continue
        row = DatedEvent(
            cik=n.issuer_cik, event_type=PROPOSED_SALE, event_date=n.filing_date,
            accession_number=n.accession_number,
            detail=json.dumps({"person_name": n.person_name, "shares": _num(n.shares),
                               "aggregate_market_value": _num(n.aggregate_market_value),
                               "approx_sale_date": n.approx_sale_date.isoformat()
                               if n.approx_sale_date else None}),
            source_url=n.source_url,
            stream_status="pending" if n.filing_date >= today - timedelta(days=FRESH_DAYS)
            else "skipped",
            created_at=utcnow(),
        )  # fmt: skip
        db.add(row)
        added.append(row)
    db.flush()
    return added
