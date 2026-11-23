"""Private raises from Form D (D-15, docs/contracts/private-raises.md).

The SEC's structured Form D data sets (quarterly) give each Form D and D/A notice: the issuers,
the offering, related persons. One row per filing is stored for the primary issuer; amendments
share the original's file number and the newest filing of each offering is marked is_latest.
Self-reported by the issuer on Form D; amounts as filed. Related persons are kept as filed and
never linked to the officer graph (exact names across issuers are not safe to join).
"""

from __future__ import annotations

import base64
import csv
import io
import json
import re
import zipfile
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

from sqlalchemy import delete, func, insert, select, update
from sqlalchemy.orm import Session

from app.db.models import FormDFiling, MartCompany
from app.services.sec_client import filing_index_url, normalize_cik

BASIS = "Self-reported by the issuer on Form D; amounts as filed."
EXEMPTIONS = {
    "06b": "Rule 506(b)", "06c": "Rule 506(c)", "04": "Rule 504", "04a": "Rule 504(b)(1)(i)",
    "04b": "Rule 504(b)(1)(ii)", "04c": "Rule 504(b)(1)(iii)", "4a5": "Section 4(a)(5)",
    "3C": "Investment Company Act 3(c)", "3C.1": "ICA 3(c)(1)", "3C.7": "ICA 3(c)(7)",
}  # fmt: skip
NOTES = [
    "Exemption codes as filed: 06b = Rule 506(b), 06c = Rule 506(c), 04 = Rule 504, "
    "4a5 = Section 4(a)(5), 3C.1-3C.7 = Investment Company Act exclusions.",
    "A Form D is a notice of an exempt offering, filed by the issuer; the SEC does not review "
    "it. Amounts are US dollars as filed.",
]
MAX_PERSONS = 10
# D-15b: a self-reported amount of $100B or more is implausible unless the issuer is a cash-
# management vehicle (their cumulative subscriptions roll over: Northern Trust Liquid Assets
# Portfolio, Western Asset Institutional Cash Reserves). The largest other raises in the data are
# about $30B (Bridgewater, Renaissance funds) and X.AI's $16.6B. Values stay as filed.
SUSPECT_AMOUNT = Decimal("100000000000")
_CASH_VEHICLE = re.compile(r"\b(cash|liquid\w*|money market|prime|treasury|reserves?|"
                           r"current asset|core funds?|series trust)\b", re.IGNORECASE)  # fmt: skip


def quality_of(issuer_name: str, offered, sold) -> str:
    big = max((v for v in (offered, sold) if v is not None), default=None)
    if big is not None and big >= SUSPECT_AMOUNT and not _CASH_VEHICLE.search(issuer_name or ""):
        return "suspect_amount"
    return "ok"
csv.field_size_limit(10_000_000)


def _rows(z: zipfile.ZipFile, name: str):
    member = next(n for n in z.namelist() if n.upper().endswith(name))
    with z.open(member) as raw:
        yield from csv.DictReader(io.TextIOWrapper(raw, encoding="latin-1", newline=""),
                                  delimiter="\t", quoting=csv.QUOTE_NONE)  # fmt: skip


def _money(v: str | None) -> Decimal | None:
    try:
        return Decimal((v or "").replace(",", "").strip())
    except InvalidOperation:
        return None


def _int(v: str | None) -> int | None:
    try:
        return int(float((v or "").strip()))
    except ValueError:
        return None


def _day(v: str | None) -> date | None:
    v = (v or "").strip()
    for fmt in ("%d-%b-%Y", "%Y-%m-%d", "%m/%d/%Y"):
        try:
            return datetime.strptime(v, fmt).date()
        except ValueError:
            continue
    return None


def parse_zip(path: str | Path) -> list[dict]:
    source = "sec:formd:" + Path(path).stem
    with zipfile.ZipFile(path) as z:
        subs = {r["ACCESSIONNUMBER"]: r for r in _rows(z, "FORMDSUBMISSION.TSV")
                if (r.get("TESTORLIVE") or "LIVE").upper() == "LIVE"}  # fmt: skip
        issuers = {}
        for r in _rows(z, "ISSUERS.TSV"):
            if (r.get("IS_PRIMARYISSUER_FLAG") or "").upper() == "YES":
                issuers[r["ACCESSIONNUMBER"]] = r
        persons: dict[str, list[dict]] = {}
        for r in _rows(z, "RELATEDPERSONS.TSV"):
            name = " ".join(x for x in (r.get("FIRSTNAME"), r.get("MIDDLENAME"),
                                        r.get("LASTNAME")) if x and x.strip())  # fmt: skip
            rel = [r[k] for k in ("RELATIONSHIP_1", "RELATIONSHIP_2", "RELATIONSHIP_3")
                   if r.get(k)]  # fmt: skip
            persons.setdefault(r["ACCESSIONNUMBER"], []).append(
                {"name": " ".join(name.split()), "relationships": rel,
                 "city": r.get("CITY") or None, "state": r.get("STATEORCOUNTRY") or None})
        out = []
        for o in _rows(z, "OFFERING.TSV"):
            acc = o["ACCESSIONNUMBER"]
            s, i = subs.get(acc), issuers.get(acc)
            if s is None or i is None or not (i.get("CIK") or "").strip():
                continue
            filed = _day(s.get("FILING_DATE"))
            if filed is None:
                continue
            total = o.get("TOTALOFFERINGAMOUNT") or ""
            ps = persons.get(acc, [])
            year = (i.get("YEAROFINC_VALUE_ENTERED") or "").strip() or None
            out.append({
                "accession_number": acc, "file_number": (s.get("FILE_NUM") or "").strip() or None,
                "form_type": (s.get("SUBMISSIONTYPE") or "D").strip(), "filing_date": filed,
                "cik": normalize_cik(i["CIK"]), "issuer_name": " ".join(i["ENTITYNAME"].split()),
                "state": i.get("STATEORCOUNTRY") or None,
                "jurisdiction": i.get("JURISDICTIONOFINC") or None,
                "entity_type": i.get("ENTITYTYPE") or None, "year_of_incorporation": year,
                "industry_group": o.get("INDUSTRYGROUPTYPE") or None,
                "total_offering_amount": None if total.strip().lower() == "indefinite"
                else _money(total),
                "indefinite": total.strip().lower() == "indefinite",
                "total_amount_sold": _money(o.get("TOTALAMOUNTSOLD")),
                "total_remaining": _money(o.get("TOTALREMAINING")),
                "investors_total": _int(o.get("TOTALNUMBERALREADYINVESTED")),
                "investors_non_accredited": _int(o.get("NUMBERNONACCREDITEDINVESTORS")),
                "first_sale_date": _day(o.get("SALE_DATE")),
                "first_sale_yet_to_occur": (o.get("YETTOOCCUR") or "").lower() == "true",
                "exemptions": ",".join(x.strip() for x in (o.get("FEDERALEXEMPTIONS_ITEMS_LIST")
                                                           or "").split(",") if x.strip())
                or None,
                "minimum_investment": _money(o.get("MINIMUMINVESTMENTACCEPTED")),
                "sales_commissions": _money(o.get("SALESCOMM_DOLLARAMOUNT")),
                "finders_fees": _money(o.get("FINDERSFEE_DOLLARAMOUNT")),
                "related_persons": json.dumps(ps[:MAX_PERSONS]),
                "related_persons_count": len(ps), "is_latest": True, "source": source,
            })  # fmt: skip
            out[-1]["quality_status"] = quality_of(out[-1]["issuer_name"],
                                                   out[-1]["total_offering_amount"],
                                                   out[-1]["total_amount_sold"])  # fmt: skip
    return out


def load(db: Session, paths: list[Path]) -> dict:
    rows = []
    for p in paths:
        rows += parse_zip(p)
    by_acc = {r["accession_number"]: r for r in rows}
    accs = sorted(by_acc)
    for i in range(0, len(accs), 2000):
        db.execute(delete(FormDFiling).where(FormDFiling.accession_number.in_(accs[i : i + 2000])))
    rows = list(by_acc.values())
    for i in range(0, len(rows), 5000):
        db.execute(insert(FormDFiling), rows[i : i + 5000])
    mark_latest(db)
    db.commit()
    return {"filings": len(rows), "offerings": db.scalar(
        select(func.count()).select_from(FormDFiling).where(FormDFiling.is_latest))}


def mark_latest(db: Session) -> None:
    """is_latest: the newest filing (date, then accession) of each file number."""
    db.execute(update(FormDFiling).values(is_latest=False))
    newest = (select(FormDFiling.file_number, func.max(FormDFiling.filing_date).label("d"))
              .where(FormDFiling.file_number.is_not(None)).group_by(FormDFiling.file_number)
              .subquery())  # fmt: skip
    cands = db.execute(select(FormDFiling.accession_number, FormDFiling.file_number).join(
        newest, (newest.c.file_number == FormDFiling.file_number)
        & (newest.c.d == FormDFiling.filing_date))).all()  # fmt: skip
    best: dict[str, str] = {}
    for acc, fno in cands:
        best[fno] = max(best.get(fno, ""), acc)
    keep = list(best.values())
    for i in range(0, len(keep), 2000):
        db.execute(update(FormDFiling).where(FormDFiling.accession_number.in_(keep[i : i + 2000]))
                   .values(is_latest=True))  # fmt: skip
    db.execute(update(FormDFiling).where(FormDFiling.file_number.is_(None)).values(is_latest=True))


# -- read --------------------------------------------------------------------------------


def _num(v):
    if v is None:
        return None
    f = float(v)
    return int(f) if f.is_integer() else f


def _filing(r: FormDFiling) -> dict:
    return {"accession_number": r.accession_number, "form": r.form_type,
            "filed_date": r.filing_date.isoformat(),
            "source_url": filing_index_url(r.cik, r.accession_number)}  # fmt: skip


def item(r: FormDFiling, chain: list[FormDFiling], registrants: set[str]) -> dict:
    persons = json.loads(r.related_persons)
    return {
        "issuer": {"cik": r.cik, "name": r.issuer_name, "state": r.state,
                   "jurisdiction": r.jurisdiction, "entity_type": r.entity_type,
                   "year_of_incorporation": r.year_of_incorporation,
                   "is_registrant": r.cik in registrants},
        "industry_group": r.industry_group,
        "total_offering_amount": _num(r.total_offering_amount),
        "total_amount_sold": _num(r.total_amount_sold),
        "total_remaining": _num(r.total_remaining), "indefinite": r.indefinite,
        "investors": {"total": r.investors_total, "non_accredited": r.investors_non_accredited},
        "first_sale_date": r.first_sale_date.isoformat() if r.first_sale_date else None,
        "first_sale_yet_to_occur": r.first_sale_yet_to_occur,
        "exemptions": (r.exemptions or "").split(",") if r.exemptions else [],
        "minimum_investment": _num(r.minimum_investment),
        "sales_commissions": _num(r.sales_commissions), "finders_fees": _num(r.finders_fees),
        "related_persons": persons, "related_persons_count": r.related_persons_count,
        "quality_status": r.quality_status,
        "latest_filing": _filing(r),
        "filings": [_filing(x) for x in sorted(chain, key=lambda x: (x.filing_date,
                                                                    x.accession_number))],
    }  # fmt: skip


def _registrants(db: Session, ciks: set[str]) -> set[str]:
    if not ciks:
        return set()
    return set(db.scalars(select(MartCompany.cik).where(
        MartCompany.cik.in_(ciks), MartCompany.latest_annual_report_date.is_not(None))))


def _items(db: Session, rows: list[FormDFiling]) -> list[dict]:
    fnos = {r.file_number for r in rows if r.file_number}
    chains: dict[str, list[FormDFiling]] = {}
    if fnos:
        for x in db.scalars(select(FormDFiling).where(FormDFiling.file_number.in_(fnos))):
            chains.setdefault(x.file_number, []).append(x)
    regs = _registrants(db, {r.cik for r in rows})
    return [item(r, chains.get(r.file_number, [r]) if r.file_number else [r], regs) for r in rows]


def encode_cursor(offset: int) -> str:
    return base64.urlsafe_b64encode(f"d:{offset}".encode()).decode().rstrip("=")


def decode_cursor(cursor: str | None) -> int:
    if not cursor:
        return 0
    raw = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)).decode()
    if not raw.startswith("d:") or not raw[2:].isdigit():
        raise ValueError("bad cursor")
    return int(raw[2:])


def search(db: Session, industry: str | None = None, state: str | None = None,
           min_amount: float | None = None, start: date | None = None, end: date | None = None,
           exemption: str | None = None, cik: str | None = None, limit: int = 50,
           offset: int = 0, min_sold: float | None = None, order: str = "date",
           include_suspect: bool = False,
           exclude_industry: str | None = None) -> tuple[list[dict], bool]:  # fmt: skip
    q = select(FormDFiling).where(FormDFiling.is_latest)
    if cik:
        q = q.where(FormDFiling.cik == cik)
    if industry:
        q = q.where(func.lower(FormDFiling.industry_group) == industry.lower())
    if state:
        q = q.where(func.upper(FormDFiling.state) == state.upper())
    if exclude_industry:  # "Largest raised" without pooled funds
        q = q.where(func.coalesce(func.lower(FormDFiling.industry_group), "")
                    != exclude_industry.lower())  # fmt: skip
    if min_amount is not None:
        amount = func.coalesce(FormDFiling.total_offering_amount, FormDFiling.total_amount_sold)
        q = q.where(amount >= min_amount)
    if start:
        q = q.where(FormDFiling.filing_date >= start)
    if end:
        q = q.where(FormDFiling.filing_date <= end)
    if exemption:
        q = q.where(("," + FormDFiling.exemptions + ",").like(f"%,{exemption},%"))
    if min_sold is not None:  # "raised": the cumulative amount sold on the latest filing
        q = q.where(FormDFiling.total_amount_sold >= min_sold)
    if (min_sold is not None or order == "sold") and not include_suspect:
        q = q.where(FormDFiling.quality_status == "ok")  # D-15b: implausible amounts left out
    if order == "sold":
        q = q.order_by(FormDFiling.total_amount_sold.desc().nulls_last(),
                       FormDFiling.accession_number.desc())  # fmt: skip
    else:
        q = q.order_by(FormDFiling.filing_date.desc(), FormDFiling.accession_number.desc())
    rows = list(db.scalars(q.offset(offset).limit(limit + 1)))
    return _items(db, rows[:limit]), len(rows) > limit


def covered_through(db: Session) -> date | None:
    """The newest filing date in the loaded data sets."""
    return db.scalar(select(func.max(FormDFiling.filing_date)))


def suspect_count(db: Session, industry=None, start=None, end=None, min_sold=None) -> int:
    """How many offerings a ranked answer left out as implausible (D-15b)."""
    q = select(func.count()).select_from(FormDFiling).where(
        FormDFiling.is_latest, FormDFiling.quality_status == "suspect_amount")
    if industry:
        q = q.where(func.lower(FormDFiling.industry_group) == industry.lower())
    if start:
        q = q.where(FormDFiling.filing_date >= start)
    if end:
        q = q.where(FormDFiling.filing_date <= end)
    if min_sold is not None:
        q = q.where(FormDFiling.total_amount_sold >= min_sold)
    return int(db.scalar(q) or 0)


def mark_quality(db: Session) -> int:
    """Recompute quality_status for every stored filing; returns how many are suspect."""
    n = 0
    for r in db.scalars(select(FormDFiling)):
        q = quality_of(r.issuer_name, r.total_offering_amount, r.total_amount_sold)
        if r.quality_status != q:
            r.quality_status = q
        n += q != "ok"
    db.flush()
    return n
