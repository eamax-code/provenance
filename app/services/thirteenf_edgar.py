"""Form 13F filings read one by one from EDGAR (launch plan E-1b), for the quarter the SEC's 13F
data sets do not cover yet.

The quarterly full index (form.idx) lists every 13F-HR, 13F-HR/A and 13F-NT with its filing date.
Each filing's complete submission text holds the cover page (primary_doc XML) and the information
table XML, so one request per filing is enough; it goes through the SEC client's machine-wide
limit. Rows are stored exactly as the data sets' are (app.services.thirteenf): shares only, no
options, values in dollars, per filing and CUSIP. Filings already stored are skipped, so a run
can stop and resume. The loaded-through date moves only when a run has read every listed filing,
so a quarter never shows half loaded.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from xml.etree import ElementTree

from sqlalchemy import insert, select
from sqlalchemy.orm import Session

from app.db.models import Filing13F, Holding13F, utcnow
from app.services import cusips as cusip_map
from app.services import thirteenf
from app.services.insiders import safe_xml
from app.services.sec_client import SecClient, SecClientError, normalize_cik

FORMS = ("13F-HR", "13F-HR/A", "13F-NT", "13F-NT/A")
_DOC = re.compile(r"(?is)<DOCUMENT>(.*?)</DOCUMENT>")
_TYPE = re.compile(r"(?im)^<TYPE>\s*([^\r\n<]+)")
_XML = re.compile(r"(?is)<XML>\s*(.*?)\s*</XML>")


def index_url(year: int, quarter: int) -> str:
    return f"https://www.sec.gov/Archives/edgar/full-index/{year}/QTR{quarter}/form.idx"


def list_filings(text: str, after: date | None = None) -> list[dict]:
    """13F filings in a form.idx: {form, cik, filed, path, accession}, filed after `after`."""
    out = []
    for line in text.splitlines():
        form = line[:17].strip()
        if form not in FORMS:
            continue
        parts = line.split()
        path, filed = parts[-1], parts[-2]
        try:
            day = datetime.strptime(filed, "%Y-%m-%d").date()
        except ValueError:
            continue
        if after and day <= after:
            continue
        cik = path.split("/")[2]
        out.append({"form": form, "cik": normalize_cik(cik), "filed": day, "path": path,
                    "accession": path.rsplit("/", 1)[-1].removesuffix(".txt")})  # fmt: skip
    return out


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _first(root, name: str) -> str | None:
    for el in root.iter():
        if _local(el.tag) == name:
            return (el.text or "").strip() or None
    return None


def _dec(value: str | None) -> Decimal | None:
    try:
        return Decimal((value or "").replace(",", "").strip())
    except InvalidOperation:
        return None


def parse_submission(text: str, item: dict) -> tuple[dict | None, list[dict]]:
    """(filing row, holdings rows) from one complete submission text."""
    cover = table = None
    for doc in _DOC.findall(text):
        kind = _TYPE.search(doc).group(1).strip().upper() if _TYPE.search(doc) else ""
        xml = _XML.search(doc)
        if not xml:
            continue
        if kind.startswith("13F") and cover is None:
            cover = safe_xml(xml.group(1))
        elif kind == "INFORMATION TABLE" and table is None:
            table = safe_xml(xml.group(1))
    if cover is None:
        return None, []
    period_raw = _first(cover, "periodOfReport") or _first(cover, "reportCalendarOrQuarter")
    period = None
    for fmt in ("%m-%d-%Y", "%m/%d/%Y", "%Y-%m-%d"):
        try:
            period = datetime.strptime(period_raw or "", fmt).date()
            break
        except ValueError:
            continue
    if period is None:
        return None, []
    form = item["form"]
    amendment = (_first(cover, "amendmentType") or "").upper() or None
    if form.endswith("/A") and amendment is None:
        amendment = "RESTATEMENT"
    total = _dec(_first(cover, "tableValueTotal"))
    entries = _first(cover, "tableEntryTotal")
    filing = {
        "accession_number": item["accession"], "filer_cik": item["cik"],
        "filer_name": " ".join((_first(cover, "name") or item["cik"]).split())[:300],
        "report_period": period, "filing_date": item["filed"], "form_type": form,
        "amendment_type": amendment if form.endswith("/A") else None,
        "report_type": _first(cover, "reportType"),
        "entry_total": int(entries) if (entries or "").isdigit() else None,
        "value_total_usd": thirteenf.dollars(total, item["filed"]) if total is not None else None,
        "confidential_omitted": (_first(cover, "isConfidentialOmitted") or "").lower() == "true",
        "source": "sec:13f-edgar",
    }  # fmt: skip
    rows: dict[str, dict] = {}
    if table is not None and form in thirteenf.HOLDINGS_FORMS:
        for info in (el for el in table.iter() if _local(el.tag) == "infoTable"):
            if (_first(info, "sshPrnamtType") or "").upper() != "SH" or _first(info, "putCall"):
                continue
            cusip = (_first(info, "cusip") or "").upper()
            shares, value = _dec(_first(info, "sshPrnamt")), _dec(_first(info, "value"))
            if not cusip_map.valid(cusip) or shares is None or value is None:
                continue
            h = rows.get(cusip)
            usd = thirteenf.dollars(value, item["filed"])
            if h is None:
                rows[cusip] = {
                    "accession_number": item["accession"], "cusip": cusip,
                    "filer_cik": item["cik"], "report_period": period,
                    "filing_date": item["filed"],
                    "title_of_class": " ".join((_first(info, "titleOfClass") or "").split())[:100]
                    or None, "shares": shares, "value_usd": usd,
                }  # fmt: skip
            else:
                h["shares"] += shares
                h["value_usd"] += usd
    return filing, list(rows.values())


def load(db: Session, sec: SecClient, items: list[dict], progress=None) -> dict:
    """Read and store each listed filing not stored yet. Returns counts; `complete` is True
    when every listed filing is stored (or unreadable and counted)."""
    have = set(db.scalars(select(Filing13F.accession_number).where(
        Filing13F.accession_number.in_([i["accession"] for i in items]))))  # fmt: skip
    out = {"listed": len(items), "already": len(have), "stored": 0, "holdings": 0, "failed": 0}
    for n, item in enumerate(items, 1):
        if item["accession"] in have:
            continue
        try:
            text = sec.get_text("https://www.sec.gov/Archives/" + item["path"]).data
            filing, rows = parse_submission(text, item)
        except (SecClientError, ValueError, ElementTree.ParseError):
            out["failed"] += 1
            continue
        if filing is None:
            out["failed"] += 1
            continue
        db.execute(insert(Filing13F), [{**filing, "created_at": utcnow()}])
        if rows:
            db.execute(insert(Holding13F), rows)
        out["stored"] += 1
        out["holdings"] += len(rows)
        if n % 200 == 0:
            db.commit()
            if progress:
                progress({**out, "done": n})
    db.commit()
    out["complete"] = out["failed"] == 0
    return out
