"""Insiders from Forms 3, 4 and 5: who reports as a director, officer or 10% owner of a company,
what they bought, sold and hold (GH #24, ADR 0011).

Two sources, one shape:
- The SEC's insider transaction data sets: every Form 3, 4 and 5 of a quarter as tab-separated
  tables, published a few weeks after the quarter ends. One download per quarter.
- For filings newer than the latest data set, the filing's own XML (the `filings` table already
  lists every Form 4 by accession, so only the gap is fetched).

Owner street addresses are in both sources and are never stored. Rows are replaced per
accession, so reloading a quarter or refetching a filing is idempotent.
"""

from __future__ import annotations

import csv
import hashlib
import io
import logging
import re
import zipfile
from collections import defaultdict
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from xml.etree import ElementTree

from sqlalchemy import delete, func, insert, select
from sqlalchemy.orm import Session

from app.core.logging import log_event
from app.db.models import Filing, InsiderDataset, InsiderFiling, InsiderTransaction, utcnow
from app.services.sec_client import SecClient, SecClientError, normalize_cik

logger = logging.getLogger("app.insiders")

DATASETS_PAGE = "https://www.sec.gov/data-research/sec-markets-data/insider-transactions-data-sets"
FORMS = ("3", "3/A", "4", "4/A", "5", "5/A")
# Transaction codes (Form 4 general instructions, 8): open-market and private purchases and sales
OPEN_MARKET = {"P": "purchase", "S": "sale"}
CODE_LABELS = {
    "P": "open-market purchase",
    "S": "open-market sale",
    "A": "grant or award",
    "M": "option exercise",
    "F": "shares withheld for tax",
    "G": "gift",
    "D": "disposition to the issuer",
    "C": "conversion",
    "X": "exercise of in-the-money option",
    "J": "other acquisition or disposition",
    "W": "acquired or disposed by will",
    "I": "discretionary transaction",
    "E": "expiration of short position",
    "H": "expiration of long position",
    "O": "exercise of out-of-the-money option",
    "K": "equity swap",
    "U": "tender of shares in a change of control",
    "V": "voluntarily reported",
    "Z": "deposit into or withdrawal from a voting trust",
    "L": "small acquisition",
}
CURRENT_YEARS = 2  # an insider who has not filed for this long is shown as former
_BATCH = 5000


# ---- parsing -----------------------------------------------------------------------------


def _date(value: str | None) -> date | None:
    value = (value or "").strip()
    if not value:
        return None
    for fmt in ("%d-%b-%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(value[:11] if fmt == "%d-%b-%Y" else value[:10], fmt).date()
        except ValueError:
            continue
    return None


def _num(value: str | None) -> Decimal | None:
    value = (value or "").strip().replace(",", "")
    if not value:
        return None
    try:
        d = Decimal(value)
    except InvalidOperation:
        return None
    return d if d.is_finite() and abs(d) < Decimal("1e19") else None


def _flag(value: str | None) -> bool | None:
    v = (value or "").strip().lower()
    if v in ("1", "true", "y"):
        return True
    if v in ("0", "false", "n"):
        return False
    return None


def _text(value: str | None, limit: int = 300) -> str | None:
    v = " ".join((value or "").split())
    return v[:limit] or None


def _owner_row(acc: str, cik: str, name: str, rel: Iterable[str], title, other) -> dict:
    rel = {r.strip().lower() for r in rel}
    return {
        "accession_number": acc,
        "owner_cik": normalize_cik(cik),
        "owner_name": _text(name, 200) or "Unknown",
        "is_director": "director" in rel,
        "is_officer": "officer" in rel,
        "is_ten_percent_owner": "tenpercentowner" in rel,
        "is_other": "other" in rel,
        "officer_title": _text(title, 200),
        "other_text": _text(other, 200),
    }


def _tx_row(acc: str, kind: str, derivative: bool, key: str, r: dict) -> dict:
    return {
        "accession_number": acc,
        "row_kind": kind,
        "is_derivative": derivative,
        "row_key": key,
        "security_title": _text(r.get("SECURITY_TITLE"), 200),
        "trans_date": _date(r.get("TRANS_DATE")),
        "trans_code": _text(r.get("TRANS_CODE"), 4),
        "shares": _num(r.get("TRANS_SHARES")),
        "price": _num(r.get("TRANS_PRICEPERSHARE")),
        "acquired_disposed": _text(r.get("TRANS_ACQUIRED_DISP_CD"), 1),
        "shares_after": _num(r.get("SHRS_OWND_FOLWNG_TRANS")),
        "direct_indirect": _text(r.get("DIRECT_INDIRECT_OWNERSHIP"), 1),
        "nature_of_ownership": _text(r.get("NATURE_OF_OWNERSHIP"), 200),
        "underlying_title": _text(r.get("UNDLYNG_SEC_TITLE"), 200),
        "underlying_shares": _num(r.get("UNDLYNG_SEC_SHARES")),
        "exercise_price": _num(r.get("CONV_EXERCISE_PRICE")),
    }


@dataclass
class Parsed:
    """Filings (by accession), their owners and their rows, ready to store."""

    filings: dict[str, dict] = field(default_factory=dict)
    owners: list[dict] = field(default_factory=list)
    rows: list[dict] = field(default_factory=list)


def _tsv(zf: zipfile.ZipFile, name: str) -> Iterator[dict]:
    member = next((n for n in zf.namelist() if n.upper().endswith(name)), None)
    if member is None:
        return
    with zf.open(member) as raw:
        text = io.TextIOWrapper(raw, encoding="utf-8", errors="replace", newline="")
        yield from csv.DictReader(text, delimiter="\t", quoting=csv.QUOTE_NONE)


def parse_dataset(path: Path, issuers: set[str] | None = None) -> Parsed:
    """One quarter's zip. `issuers` keeps only those issuer CIKs (None keeps all)."""
    out = Parsed()
    with zipfile.ZipFile(path) as zf:
        for r in _tsv(zf, "SUBMISSION.TSV"):
            form = (r.get("DOCUMENT_TYPE") or "").strip()
            filed = _date(r.get("FILING_DATE"))
            try:
                issuer = normalize_cik(r.get("ISSUERCIK") or "")
            except ValueError:
                continue
            if (
                form not in FORMS
                or filed is None
                or (issuers is not None and issuer not in issuers)
            ):
                continue
            out.filings[r["ACCESSION_NUMBER"].strip()] = {
                "issuer_cik": issuer,
                "form_type": form,
                "filing_date": filed,
                "period_of_report": _date(r.get("PERIOD_OF_REPORT")),
                "plan_10b5_1": _flag(r.get("AFF10B5ONE")),
            }
        seen: set[tuple[str, str]] = set()
        for r in _tsv(zf, "REPORTINGOWNER.TSV"):
            acc = r["ACCESSION_NUMBER"].strip()
            cik = (r.get("RPTOWNERCIK") or "").strip()
            if acc not in out.filings or not cik.isdigit() or (acc, cik) in seen:
                continue
            seen.add((acc, cik))
            rel = (r.get("RPTOWNER_RELATIONSHIP") or "").split(",")
            out.owners.append(
                _owner_row(
                    acc,
                    cik,
                    r.get("RPTOWNERNAME") or "",
                    rel,
                    r.get("RPTOWNER_TITLE"),
                    r.get("RPTOWNER_TXT"),
                )  # fmt: skip
            )
        for name, kind, deriv in (
            ("NONDERIV_TRANS.TSV", "transaction", False),
            ("NONDERIV_HOLDING.TSV", "holding", False),
            ("DERIV_TRANS.TSV", "transaction", True),
            ("DERIV_HOLDING.TSV", "holding", True),
        ):
            sk = name.replace(".TSV", "_SK")
            for r in _tsv(zf, name):
                acc = r["ACCESSION_NUMBER"].strip()
                if acc in out.filings:
                    out.rows.append(_tx_row(acc, kind, deriv, (r.get(sk) or "").strip(), r))
    return out


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _find(node, path: str) -> str | None:
    """Text of the first descendant matching a slash path of local names; <value> is unwrapped."""
    cur = [node]
    for part in path.split("/"):
        cur = [c for n in cur for c in n if _local(c.tag) == part]
        if not cur:
            return None
    n = cur[0]
    val = next((c for c in n if _local(c.tag) == "value"), None)
    return ((val if val is not None else n).text or "").strip() or None


def safe_xml(text: str):
    """Parse an EDGAR XML document. Documents that declare a DTD or entities are refused."""
    head = text[:4096].upper()
    if "<!DOCTYPE" in head or "<!ENTITY" in text.upper():
        raise ValueError("XML with a DTD or entities is not accepted")
    return ElementTree.fromstring(text.encode("utf-8"))


_XML_FLAGS = (
    ("isDirector", "director"),
    ("isOfficer", "officer"),
    ("isTenPercentOwner", "tenpercentowner"),
    ("isOther", "other"),
)


def parse_ownership_xml(text: str, accession: str, filing_date: date) -> Parsed:
    """One Form 3, 4 or 5 XML (ownershipDocument) in the data set's shape."""
    root = safe_xml(text)
    out = Parsed()
    form = _find(root, "documentType") or ""
    issuer = _find(root, "issuer/issuerCik") or ""
    if form not in FORMS or not issuer.isdigit():
        return out
    out.filings[accession] = {
        "issuer_cik": normalize_cik(issuer),
        "form_type": form,
        "filing_date": filing_date,
        "period_of_report": _date(_find(root, "periodOfReport")),
        "plan_10b5_1": _flag(_find(root, "aff10b5One")),
    }
    for ro in (c for c in root if _local(c.tag) == "reportingOwner"):
        cik = _find(ro, "reportingOwnerId/rptOwnerCik") or ""
        if not cik.isdigit():
            continue
        rel = ro.find("{*}reportingOwnerRelationship")
        flags = []
        for tag, word in _XML_FLAGS:
            if rel is not None and _flag(_find(rel, tag)):
                flags.append(word)
        out.owners.append(
            _owner_row(
                accession,
                cik,
                _find(ro, "reportingOwnerId/rptOwnerName") or "",
                flags,
                _find(rel, "officerTitle") if rel is not None else None,
                _find(rel, "otherText") if rel is not None else None,
            )  # fmt: skip
        )
    tables = (
        ("nonDerivativeTable", "nonDerivativeTransaction", "transaction", False),
        ("nonDerivativeTable", "nonDerivativeHolding", "holding", False),
        ("derivativeTable", "derivativeTransaction", "transaction", True),
        ("derivativeTable", "derivativeHolding", "holding", True),
    )
    for table, tag, kind, deriv in tables:
        t = next((c for c in root if _local(c.tag) == table), None)
        if t is None:
            continue
        for i, n in enumerate(c for c in t if _local(c.tag) == tag):
            r = {
                "SECURITY_TITLE": _find(n, "securityTitle"),
                "TRANS_DATE": _find(n, "transactionDate"),
                "TRANS_CODE": _find(n, "transactionCoding/transactionCode"),
                "TRANS_SHARES": _find(n, "transactionAmounts/transactionShares"),
                "TRANS_PRICEPERSHARE": _find(n, "transactionAmounts/transactionPricePerShare"),
                "TRANS_ACQUIRED_DISP_CD": _find(
                    n, "transactionAmounts/transactionAcquiredDisposedCode"
                ),
                "SHRS_OWND_FOLWNG_TRANS": _find(
                    n, "postTransactionAmounts/sharesOwnedFollowingTransaction"
                ),
                "DIRECT_INDIRECT_OWNERSHIP": _find(n, "ownershipNature/directOrIndirectOwnership"),
                "NATURE_OF_OWNERSHIP": _find(n, "ownershipNature/natureOfOwnership"),
                "UNDLYNG_SEC_TITLE": _find(n, "underlyingSecurity/underlyingSecurityTitle"),
                "UNDLYNG_SEC_SHARES": _find(n, "underlyingSecurity/underlyingSecurityShares"),
                "CONV_EXERCISE_PRICE": _find(n, "conversionOrExercisePrice"),
            }
            out.rows.append(_tx_row(accession, kind, deriv, f"x{i}", r))
    return out


# ---- storing -----------------------------------------------------------------------------


def _chunks(items: list, size: int) -> Iterator[list]:
    for i in range(0, len(items), size):
        yield items[i : i + size]


def store(db: Session, parsed: Parsed, source: str) -> tuple[int, int]:
    """Replace the given filings' owners and rows. Returns (owner rows, transaction rows)."""
    accs = list(parsed.filings)
    for chunk in _chunks(accs, 500):
        db.execute(delete(InsiderFiling).where(InsiderFiling.accession_number.in_(chunk)))
        db.execute(delete(InsiderTransaction).where(InsiderTransaction.accession_number.in_(chunk)))
    owners = [{**o, **parsed.filings[o["accession_number"]], "source": source}
              for o in parsed.owners]  # fmt: skip
    rows = [{**r, "issuer_cik": parsed.filings[r["accession_number"]]["issuer_cik"]}
            for r in parsed.rows]  # fmt: skip
    for chunk in _chunks(owners, _BATCH):
        db.execute(insert(InsiderFiling), chunk)
    for chunk in _chunks(rows, _BATCH):
        db.execute(insert(InsiderTransaction), chunk)
    return len(owners), len(rows)


def discover_datasets(client: SecClient) -> dict[str, str]:
    """Quarter -> download URL, read from the SEC's data set page."""
    page = client.get_text(DATASETS_PAGE).data
    found = {}
    for href, q in re.findall(r'href="([^"]*/(\d{4}q[1-4])_form345\.zip)"', page):
        found[q] = href if href.startswith("http") else "https://www.sec.gov" + href
    return dict(sorted(found.items()))


def load_dataset(db: Session, path: Path, quarter: str, issuers: set[str] | None = None) -> dict:
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    prev = db.get(InsiderDataset, quarter)
    if prev is not None and prev.sha256 == digest:
        return {"quarter": quarter, "skipped": True}
    parsed = parse_dataset(path, issuers)
    n_owners, n_rows = store(db, parsed, f"dataset:{quarter}")
    last = max((f["filing_date"] for f in parsed.filings.values()), default=None)
    if prev is None:
        prev = InsiderDataset(quarter=quarter, sha256=digest)
        db.add(prev)
    prev.sha256, prev.filings, prev.rows = digest, len(parsed.filings), n_rows
    prev.last_filing_date, prev.loaded_at = last, utcnow()
    db.commit()
    stats = {"quarter": quarter, "filings": len(parsed.filings), "owners": n_owners,
             "rows": n_rows, "last_filing_date": last and last.isoformat()}  # fmt: skip
    log_event(logger, logging.INFO, "insider dataset loaded", **stats)
    return stats


def dataset_coverage(db: Session) -> date | None:
    """The newest filing date the loaded data sets cover."""
    return db.scalar(select(func.max(InsiderDataset.last_filing_date)))


def _xml_url(f: Filing) -> str | None:
    doc = (f.primary_document or "").split("/")[-1]
    if not doc.lower().endswith(".xml"):
        return None
    base = f.source_url.rsplit("/", 1)[0]
    return f"{base}/{doc}"


def fill_recent(db: Session, client: SecClient, cik: str, limit: int = 40) -> dict:
    """Fetch Forms 3, 4 and 5 about `cik` filed after the newest loaded data set."""
    cik = normalize_cik(cik)
    since = dataset_coverage(db) or (date.today() - timedelta(days=120))
    have = select(InsiderFiling.accession_number).where(InsiderFiling.issuer_cik == cik)
    todo = db.scalars(
        select(Filing)
        .where(Filing.cik == cik, Filing.form_type.in_(FORMS), Filing.filing_date > since)
        .where(Filing.accession_number.not_in(have))
        .order_by(Filing.filing_date.desc())
        .limit(limit)
    ).all()
    fetched = failed = 0
    for f in todo:
        url = _xml_url(f)
        if url is None:
            continue
        try:
            text = client.get_text(url).data
            parsed = parse_ownership_xml(text, f.accession_number, f.filing_date)
        except (SecClientError, ValueError, ElementTree.ParseError):
            failed += 1
            continue
        if parsed.filings:
            store(db, parsed, "filing")
            fetched += 1
    db.commit()
    return {"cik": cik, "since": since.isoformat(), "fetched": fetched, "failed": failed,
            "pending": len(todo)}  # fmt: skip


# ---- reading -----------------------------------------------------------------------------

_ENTITY = re.compile(
    r"\b(inc|corp|corporation|co|company|llc|l\.l\.c|lp|l\.p|llp|ltd|limited|plc|fund|funds|"
    r"trust|holdings?|capital|partners|management|group|bank|associates|advisors|advisers|"
    r"investments?|ventures|foundation|sa|ag|nv|bv|gmbh|se|ab|asa|kk)\b\.?",
    re.I,
)


def is_entity(name: str) -> bool:
    return bool(_ENTITY.search(name or ""))


def display_name(name: str) -> str:
    """'COOK TIMOTHY D' -> 'Timothy D Cook'. EDGAR files people last name first; entity names
    are kept as filed. The name as filed is always returned alongside."""
    name = " ".join((name or "").split())
    if not name or is_entity(name) or " " not in name:
        return name
    last, rest = name.split(" ", 1)
    out = f"{rest} {last}"
    if out.isupper():
        out = re.sub(r"[A-Z]+", lambda m: m.group(0)[0] + m.group(0)[1:].lower(), out)
        out = re.sub(r"\bMc([a-z])", lambda m: "Mc" + m.group(1).upper(), out)
    return out


def role_label(r) -> str:
    parts = []
    if r["is_officer"]:
        parts.append(r["officer_title"] or "Officer")
    if r["is_director"]:
        parts.append("Director")
    if r["is_ten_percent_owner"]:
        parts.append("10% owner")
    if r["is_other"] and not parts:
        parts.append(r["other_text"] or "Other")
    return ", ".join(parts) or "Reporting person"


def _flags(r: InsiderFiling) -> dict:
    return {
        "is_director": r.is_director,
        "is_officer": r.is_officer,
        "is_ten_percent_owner": r.is_ten_percent_owner,
        "is_other": r.is_other,
        "officer_title": r.officer_title,
        "other_text": r.other_text,
    }


def roles(db: Session, cik: str, as_of: date | None = None) -> list[dict]:
    """Every reporting owner of `cik`, with the roles of their latest filing, first and last
    filing dates and filing count; `as_of` keeps only filings made by that date."""
    stmt = select(InsiderFiling).where(InsiderFiling.issuer_cik == normalize_cik(cik))
    if as_of:
        stmt = stmt.where(InsiderFiling.filing_date <= as_of)
    by_owner: dict[str, list[InsiderFiling]] = defaultdict(list)
    for r in db.scalars(stmt.order_by(InsiderFiling.filing_date, InsiderFiling.accession_number)):
        by_owner[r.owner_cik].append(r)
    today = as_of or date.today()
    out = []
    for owner, rows in by_owner.items():
        last = rows[-1]
        latest = _flags(last)
        out.append(
            {
                "owner_cik": owner,
                "name": display_name(last.owner_name),
                "name_as_filed": last.owner_name,
                "kind": "entity" if is_entity(last.owner_name) else "person",
                **latest,
                "role": role_label(latest),
                "first_filed": rows[0].filing_date,
                "last_filed": last.filing_date,
                "filings": len(rows),
                "current": (today - last.filing_date).days <= 365 * CURRENT_YEARS,
                "last_accession": last.accession_number,
                "last_form": last.form_type,
                "accessions": [r.accession_number for r in rows],
            }
        )
    out.sort(key=lambda o: (not o["current"], not o["is_officer"], not o["is_director"],
                            o["name"].lower()))  # fmt: skip
    return out


def activity(db: Session, cik: str, owners: list[dict], as_of: date | None = None) -> None:
    """Adds open-market buys and sells over the last 12 months and shares held after the latest
    report to each owner in `owners` (from roles()). Joint filings count for every owner."""
    cik = normalize_cik(cik)
    end = as_of or date.today()
    start = end - timedelta(days=365)
    acc_owner: dict[str, list[str]] = defaultdict(list)
    for o in owners:
        for a in o["accessions"]:
            acc_owner[a].append(o["owner_cik"])
    stmt = select(InsiderTransaction).where(
        InsiderTransaction.issuer_cik == cik, InsiderTransaction.is_derivative.is_(False)
    )
    rows = db.scalars(stmt).all()
    stats = {o["owner_cik"]: {"bought": Decimal(0), "sold": Decimal(0), "buys": 0, "sells": 0}
             for o in owners}  # fmt: skip
    last_acc = {o["owner_cik"]: o["last_accession"] for o in owners}
    held: dict[str, dict[tuple, Decimal]] = defaultdict(dict)
    for t in rows:
        for owner in acc_owner.get(t.accession_number, ()):
            if (
                t.row_kind == "transaction"
                and t.trans_code in OPEN_MARKET
                and t.trans_date
                and start < t.trans_date <= end
                and t.shares
            ):
                value = t.shares * (t.price or 0)
                if t.trans_code == "P":
                    stats[owner]["bought"] += value
                    stats[owner]["buys"] += 1
                else:
                    stats[owner]["sold"] += value
                    stats[owner]["sells"] += 1
            if t.accession_number == last_acc[owner] and t.shares_after is not None:
                key = (t.security_title, t.direct_indirect, t.nature_of_ownership)
                held[owner][key] = t.shares_after  # the last row per holding wins
    for o in owners:
        s = stats[o["owner_cik"]]
        o["open_market_12m"] = {
            "bought_value": float(round(s["bought"], 2)),
            "sold_value": float(round(s["sold"], 2)),
            "buys": s["buys"],
            "sells": s["sells"],
        }
        h = held.get(o["owner_cik"])
        o["shares_held"] = float(sum(h.values())) if h else None


def transactions(
    db: Session, cik: str, as_of: date | None = None, since: date | None = None,
    codes: set[str] | None = None, owner_cik: str | None = None, limit: int = 50,
    offset: int = 0,
) -> tuple[list[tuple[InsiderTransaction, InsiderFiling]], bool]:  # fmt: skip
    """Transactions about `cik`, newest first, each with one of its filing's owners."""
    cik = normalize_cik(cik)
    stmt = (
        select(InsiderTransaction, InsiderFiling)
        .join(InsiderFiling, InsiderFiling.accession_number == InsiderTransaction.accession_number)
        .where(InsiderTransaction.issuer_cik == cik, InsiderTransaction.row_kind == "transaction")
    )
    if as_of:
        stmt = stmt.where(InsiderFiling.filing_date <= as_of)
    if since:
        stmt = stmt.where(InsiderTransaction.trans_date >= since)
    if codes:
        stmt = stmt.where(InsiderTransaction.trans_code.in_(sorted(codes)))
    if owner_cik:
        stmt = stmt.where(InsiderFiling.owner_cik == normalize_cik(owner_cik))
    stmt = stmt.order_by(
        InsiderTransaction.trans_date.desc().nulls_last(),
        InsiderTransaction.accession_number.desc(),
        InsiderTransaction.id,
    )
    rows = db.execute(stmt.offset(offset).limit(limit + 1)).all()
    return [(r[0], r[1]) for r in rows[:limit]], len(rows) > limit


def other_roles(
    db: Session, owner_ciks: list[str], exclude_cik: str, as_of: date | None = None
) -> dict[str, list[dict]]:
    """For each owner, the other companies they report on (board interlocks and other roles),
    with the role of their latest filing there."""
    if not owner_ciks:
        return {}
    out: dict[str, dict[str, InsiderFiling]] = defaultdict(dict)
    for chunk in _chunks(owner_ciks, 500):
        stmt = select(InsiderFiling).where(
            InsiderFiling.owner_cik.in_(chunk), InsiderFiling.issuer_cik != exclude_cik
        )
        if as_of:
            stmt = stmt.where(InsiderFiling.filing_date <= as_of)
        for r in db.scalars(stmt.order_by(InsiderFiling.filing_date)):
            out[r.owner_cik][r.issuer_cik] = r  # the latest per issuer wins
    today = as_of or date.today()
    result: dict[str, list[dict]] = {}
    for owner, issuers in out.items():
        result[owner] = [
            {
                "issuer_cik": i,
                "role": role_label(_flags(r)),
                "is_director": r.is_director,
                "is_officer": r.is_officer,
                "is_ten_percent_owner": r.is_ten_percent_owner,
                "last_filed": r.filing_date,
                "last_accession": r.accession_number,
                "current": (today - r.filing_date).days <= 365 * CURRENT_YEARS,
            }
            for i, r in issuers.items()
        ]
    return result
