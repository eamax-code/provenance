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

import csv
import re
from datetime import date
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.db.models import CompanyLei, IssuerCusip, ListedInstrument, utcnow
from app.services.insiders import _local, safe_xml
from app.services.sec_client import normalize_cik

PRIORITY = {"schedule_13dg": 3, "isin": 2, "13f_issuer_name": 1, "issuer_prefix": 1}
# EDGAR conformed names and 13F issuer names end with a state of incorporation ("BERKSHIRE
# HATHAWAY INC DEL", "/DE/"): dropped when they are the last word
_STATE_SUFFIX = {"DEL", "DE", "NEV", "NV", "TEX", "TX", "MD", "NJ", "PA", "VA", "IND", "ILL",
                 "MASS", "CALIF", "WIS", "COLO", "MINN", "MICH", "FLA", "GA", "MO", "NY", "NEW",
                 "OLD", "COM"}  # fmt: skip
MIN_FILERS = 20
MIN_NAME_SHARE = 0.6
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


# a 13F issuer name that names another kind of security, whatever the managers' title says
# (STIFEL FINL CORP DEP: depositary shares of a preferred; MOVANO ... WARRANT): whole words only,
# so UNITED or NOTEWORTHY never trigger it
_NOT_COMMON = re.compile(
    r"\b(DEP|DEPOSITARY|PFD|PREFERRED|WARRANTS?|WTS?|RIGHTS?|UNITS?|NOTES?)\b", re.I
)


def names_other_security(issuer_name: str | None) -> bool:
    return bool(_NOT_COMMON.search(issuer_name or ""))


REVIEWED_REMOVALS = Path(__file__).resolve().parents[1] / "data" / "cusip_removals_reviewed.csv"


def _issuer(name: str) -> str:
    return " ".join(name.upper().split())


def reviewed_removals(path: Path = REVIEWED_REMOVALS) -> set[tuple[str, str]]:
    """(cik, 13F issuer name) of each issuer_prefix link checked by hand and to be removed."""
    with open(path, newline="") as fh:
        rows = list(csv.DictReader(fh))
    return {(normalize_cik(r["cik"]), _issuer(r["issuer_name_13f"])) for r in rows}


def remove_reviewed(
    db: Session, names: dict[str, set[str]], reviewed: set[tuple[str, str]]
) -> list[tuple[str, str]]:
    """Delete the issuer_prefix links whose company and 13F issuer name are on the reviewed list.
    `names` is {cusip: issuer names the 13Fs give}. Returns (cik, issuer name) per removal; no
    other link is touched."""
    rows = db.execute(
        select(IssuerCusip.cusip, IssuerCusip.cik).where(IssuerCusip.method == "issuer_prefix")
    ).all()
    gone: list[tuple[str, str]] = []
    for cusip, cik in rows:
        hit = next((n for n in sorted(names.get(cusip, ())) if (cik, _issuer(n)) in reviewed), None)
        if hit:
            db.execute(delete(IssuerCusip).where(IssuerCusip.cusip == cusip))
            gone.append((cik, _issuer(hit)))
    return gone


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


def name_key(name: str | None) -> str:
    """Company and 13F issuer names compared alike: 'JPMORGAN CHASE & CO' == 'JPMorgan Chase &
    Co.'; 'BERKSHIRE HATHAWAY INC DEL' == 'BERKSHIRE HATHAWAY INC'."""
    from app.services.successions import name_key as base

    words = re.sub(r"[^A-Z0-9 ]", " ", (name or "").upper().replace("&", " AND ")).split()
    while words and words[-1] in _STATE_SUFFIX:
        words.pop()
    return base(" ".join(words))


# Forms 13F abbreviate issuer names ("STATE STR CORP", "XYZ HLDGS INC"); only expansions with one
# meaning are used (TR and COS are not: trust or trustee, companies or a word part)
ABBREVIATIONS = {"STR": "STREET", "HLDGS": "HOLDINGS", "HLDG": "HOLDING", "INTL": "INTERNATIONAL",
                 "GRP": "GROUP", "FINL": "FINANCIAL", "SVCS": "SERVICES", "MGMT": "MANAGEMENT",
                 "PPTYS": "PROPERTIES", "RLTY": "REALTY", "SYS": "SYSTEMS",
                 "ENTMT": "ENTERTAINMENT", "BANCSHS": "BANCSHARES"}  # fmt: skip
EXPAND = True  # switched so a dry run can count what the expansion adds
TIE_BREAK = True  # one active listed company among several with the same name


_FORMS = {"INC": "INC", "INCORPORATED": "INC", "CORP": "CORP", "CORPORATION": "CORP",
          "CO": "CO", "COMPANY": "CO", "LTD": "LTD", "LIMITED": "LTD", "PLC": "PLC",
          "LLC": "LLC", "LP": "LP", "AG": "AG", "SA": "SA", "NV": "NV", "SE": "SE"}  # fmt: skip


def legal_form(name: str | None) -> str | None:
    """The last legal-form word of a name ('LAZARD LTD' -> LTD; 'Lazard, Inc.' -> INC), skipping
    state suffixes and NEW/DEL; None when it has none."""
    words = re.sub(r"[^A-Z0-9 ]", " ", (name or "").upper()).split()
    for w in reversed(words):
        if w in _FORMS:
            return _FORMS[w]
        if w not in _STATE_SUFFIX and w not in ("NEW", "WIS", "MD"):
            return None
    return None


def name_key_13f(name: str | None) -> str:
    """name_key with 13F abbreviations expanded (both sides are keyed this way)."""
    if not EXPAND:
        return name_key(name)
    words = re.sub(r"[^A-Z0-9 ]", " ", (name or "").upper().replace("&", " AND ")).split()
    return name_key(" ".join(ABBREVIATIONS.get(w, w) for w in words))


def map_by_13f_names(db: Session, names: dict[str, dict], ciks: list[str] | None = None) -> list:
    """E-1c, for companies no 13D/G or ISIN maps: a CUSIP whose dominant 13F issuer name equals the
    company's name once normalised, uniquely, given by at least MIN_FILERS managers with at least
    MIN_NAME_SHARE of them agreeing, titled as a share class, on an issuer number not mapped to
    another company. Returns the (cik, cusip, issuer name) pairs stored (medium confidence)."""
    from datetime import timedelta

    from app.db.models import Company, MartCompany

    companies = db.execute(select(Company.cik, Company.legal_name)).all()
    legal_names = dict(companies)
    by_key: dict[str, set] = {}
    for cik, legal in companies:
        k = name_key_13f(legal)
        if len(k) >= 4:
            by_key.setdefault(k, set()).add(cik)
    # active and listed: a ticker and an annual report in the last two years (the tie-break)
    recent = date.today() - timedelta(days=730)
    listed_active = set(db.scalars(
        select(Company.cik).join(MartCompany, MartCompany.cik == Company.cik)
        .where(Company.ticker.is_not(None), MartCompany.latest_annual_report_date >= recent)
    ))  # fmt: skip
    mapped = db.execute(select(IssuerCusip.cusip, IssuerCusip.cik)).all()
    have_cusip = {c for c, _ in mapped}
    prefix_owner: dict[str, set] = {}
    for c, cik in mapped:
        prefix_owner.setdefault(c[:6], set()).add(cik)
    wanted = set(ciks) if ciks else None
    stored = []
    for cusip, info in names.items():
        if cusip in have_cusip or info["filers"] < MIN_FILERS or info["share"] < MIN_NAME_SHARE:
            continue
        if not is_share_class(info["title"]):
            continue
        hits = by_key.get(name_key_13f(info["name"]), set())
        if len(hits) > 1 and TIE_BREAK:
            # the old Howard Hughes Corp beside Howard Hughes Holdings: only an exactly-one
            # active listed company takes it, and only when the legal forms agree, since the key
            # drops them and a stale 13F line can name a predecessor (MEDTRONIC INC is not
            # Medtronic plc; LAZARD LTD is not Lazard, Inc.)
            # a 13F name without a legal form confirms nothing (FARMERS & MERCHANTS BANCORP is
            # the Ohio bank's line, not the Californian one with no form in its name either)
            form = legal_form(info["name"])
            hits = {c for c in hits & listed_active
                    if form is not None and legal_form(legal_names[c]) == form}  # fmt: skip
        if len(hits) != 1:
            continue
        cik = next(iter(hits))
        if wanted is not None and cik not in wanted:
            continue
        owners = prefix_owner.get(cusip[:6], set())
        if owners and owners != {cik}:
            continue  # the issuer number belongs to another company
        if record(db, cik, cusip, "13f_issuer_name", info["title"]):
            stored.append((cik, cusip, info["name"]))
    return stored
