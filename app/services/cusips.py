"""Internal CUSIP -> company map, to join Form 13F positions to companies (launch plan E-1).

A CUSIP is never returned by the API (owner rule); this module only answers "which CUSIPs are
this company's shares". Sources, strongest first:

- schedule_13dg: a structured Schedule 13D or 13G names the issuer's CIK and the CUSIP of the
  class it reports on, in one document filed with the SEC.
- isin: a US or CA ISIN (which wraps the CUSIP) of a listing whose issuer LEI is linked to the CIK.
- issuer_prefix: another share class of an issuer already mapped (same 6-character issuer
  number) that Forms 13F title as a share class (CL A, CL C, COM), never a preferred, warrant,
  unit, right or note.

A CUSIP mapped to one CIK is moved to another only by a stronger source, or by the same source
in a later filing (a holding-company reorganisation gives the new parent a new CUSIP, so this is
rare).
"""

from __future__ import annotations

import re
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import CompanyLei, IssuerCusip, ListedInstrument, utcnow
from app.services.insiders import _local, safe_xml
from app.services.sec_client import normalize_cik

PRIORITY = {"schedule_13dg": 3, "isin": 2, "issuer_prefix": 1}
_SHAPE = re.compile(r"^[0-9A-Z*@#]{8}[0-9]$")
_EXTRA = {"*": 36, "@": 37, "#": 38}
# a share class as Forms 13F title it, and what is not one
_SHARE_CLASS = re.compile(
    r"^(COM|COMMON|CL\s?[A-Z]\b|CLASS\s?[A-Z]\b|CAP STK|ORD|SHS|SH BEN INT|COM CL\s?[A-Z])", re.I
)
_NOT_SHARES = re.compile(
    r"PFD|PREF|WT|WARRANT|UNIT|RIGHT|RTS|NOTE|BOND|DEB|CONV|DEP|SPON|ADR|ADS|ETF|FUND|TR UNIT",
    re.I,
)


def check_digit(first8: str) -> int:
    total = 0
    for i, ch in enumerate(first8):
        if ch.isdigit():
            v = int(ch)
        elif ch.isalpha():
            v = ord(ch) - 55  # A = 10
        else:
            v = _EXTRA[ch]
        if i % 2 == 1:
            v *= 2
        total += v // 10 + v % 10
    return (10 - total % 10) % 10


def valid(cusip: str | None) -> bool:
    c = (cusip or "").strip().upper()
    return bool(_SHAPE.match(c)) and check_digit(c[:8]) == int(c[8])


def from_isin(isin: str | None) -> str | None:
    """The CUSIP inside a US or CA ISIN."""
    i = (isin or "").strip().upper()
    if len(i) == 12 and i[:2] in ("US", "CA") and valid(i[2:11]):
        return i[2:11]
    return None


def is_share_class(title: str | None) -> bool:
    t = (title or "").strip()
    return bool(_SHARE_CLASS.match(t)) and not _NOT_SHARES.search(t)


def from_schedule(text: str) -> dict:
    """{issuer_cik, class_title, cusips} from a structured Schedule 13D or 13G document."""
    root = safe_xml(text)
    issuer, title, found = None, None, []
    for n in root.iter():
        tag = _local(n.tag)
        if tag in ("issuerCik", "issuerCIK") and issuer is None:
            issuer = (n.text or "").strip()
        elif tag == "securitiesClassTitle" and title is None:
            title = " ".join((n.text or "").split())[:200] or None
        elif tag == "issuerCusipNumber":
            c = (n.text or "").strip().upper().replace(" ", "")
            if valid(c) and c not in found:
                found.append(c)
    return {
        "issuer_cik": normalize_cik(issuer) if issuer and issuer.isdigit() else None,
        "class_title": title,
        "cusips": found,
    }


def record(
    db: Session,
    cik: str,
    cusip: str,
    method: str,
    class_title: str | None = None,
    accession_number: str | None = None,
    filing_date: date | None = None,
) -> bool:
    """Add or update one mapping; True when stored. See the module doc for precedence."""
    cusip = cusip.strip().upper()
    if not valid(cusip):
        return False
    row = db.get(IssuerCusip, cusip)
    if row is not None:
        stronger = PRIORITY[method] > PRIORITY[row.method]
        later = PRIORITY[method] == PRIORITY[row.method] and (filing_date or date.min) > (
            row.filing_date or date.min
        )
        if not (stronger or later or (row.cik == cik and row.method == method)):
            return False
        row.class_title = class_title or row.class_title
    else:
        row = IssuerCusip(cusip=cusip, class_title=class_title)
        db.add(row)
    row.cik, row.method = cik, method
    row.accession_number, row.filing_date = accession_number, filing_date
    row.updated_at = utcnow()
    db.flush()  # so the next lookup of this CUSIP in the session finds it
    return True


def record_schedule(db: Session, text: str, accession_number: str, filing_date: date) -> int:
    """Map the CUSIPs a structured Schedule 13D or 13G names to its issuer."""
    s = from_schedule(text)
    if not s["issuer_cik"]:
        return 0
    return sum(
        record(db, s["issuer_cik"], c, "schedule_13dg", s["class_title"], accession_number,
               filing_date)
        for c in s["cusips"]
    )  # fmt: skip


def map_isins(db: Session) -> int:
    """US and CA ISINs of listings whose issuer LEI is linked to an SEC filer."""
    rows = db.execute(
        select(ListedInstrument.isin, CompanyLei.cik)
        .join(CompanyLei, CompanyLei.lei == ListedInstrument.issuer_lei)
        .where(ListedInstrument.isin.is_not(None))
    ).all()
    n = 0
    for isin, cik in rows:
        c = from_isin(isin)
        if c:
            n += record(db, cik, c, "isin")
    return n


def map_prefixes(db: Session, classes: dict[str, str]) -> int:
    """Other share classes of mapped issuers. `classes` is {cusip: title of class} as seen on
    Forms 13F. Only issuer numbers mapped to a single CIK are extended."""
    mapped = db.execute(select(IssuerCusip.cusip, IssuerCusip.cik)).all()
    by_prefix: dict[str, set[str]] = {}
    for c, cik in mapped:
        by_prefix.setdefault(c[:6], set()).add(cik)
    known = {c for c, _ in mapped}
    n = 0
    for c, title in classes.items():
        ciks = by_prefix.get(c[:6])
        if c in known or not ciks or len(ciks) != 1 or not is_share_class(title):
            continue
        n += record(db, next(iter(ciks)), c, "issuer_prefix", title)
    return n


def cusips_for(db: Session, cik: str) -> list[IssuerCusip]:
    return list(db.scalars(select(IssuerCusip).where(IssuerCusip.cik == cik)))
