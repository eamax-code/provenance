"""Who audits a company (launch plan E-3), from the cover tags of its annual reports.

Since 2021 every 10-K, 20-F and 40-F tags the audit firm: dei:AuditorName, dei:AuditorFirmId
(the firm's PCAOB ID) and dei:AuditorLocation. The SEC's Financial Statement and Notes data sets
carry these text facts (txt.tsv) with the filing's details (sub.tsv), so no filing is fetched one
by one. A report filed after a change of auditor names both firms, each in its own context; the
context's end date says which year each audited, so the current firm is the one that audited the
report's own period.

Auditor changes are also announced in 8-K item 4.01 (changes in registrant's certifying
accountant); those filings are listed with the auditor history. Engagement partners (PCAOB Form
AP) are not included.
"""

from __future__ import annotations

import csv
import io
import zipfile
from datetime import date, datetime
from pathlib import Path

from sqlalchemy import delete, insert, select
from sqlalchemy.orm import Session

from app.db.models import CompanyAuditor, Filing
from app.services.sec_client import filing_index_url, normalize_cik

ANNUAL = ("10-K", "10-K/A", "10-KT", "10-KT/A", "20-F", "20-F/A", "40-F", "40-F/A")
AUDITOR_TAGS = {"AuditorName": "name", "AuditorFirmId": "firm_id", "AuditorLocation": "location"}
SYMBOL_TAGS = {"TradingSymbol": "symbol", "SecurityExchangeName": "exchange",
               "Security12bTitle": "title",
               "EntityRegistrantName": "registrant"}  # fmt: skip  # K-04b and K-06, one pass
CHANGE_ITEM = "4.01"
NOTES = [
    "The audit firm is as tagged on the cover of each annual report (dei:AuditorName, "
    "AuditorFirmId, AuditorLocation); the firm ID is the PCAOB's.",
    "8-K item 4.01 filings announce a change of certifying accountant; a firm change between two "
    "consecutive annual reports links the 4.01 filed between them, when there is one.",
]

csv.field_size_limit(50_000_000)


def _ymd(value: str | None) -> date | None:
    try:
        return datetime.strptime((value or "").strip()[:8], "%Y%m%d").date()
    except ValueError:
        return None


def firm_id(value: str | None) -> str | None:
    v = (value or "").strip()
    return str(int(v)) if v.isdigit() else (v or None)


def _member(z: zipfile.ZipFile, name: str) -> str | None:
    return next((n for n in z.namelist() if n.lower().endswith(name)), None)


def parse_notes_zip(path: str | Path) -> tuple[list[dict], list[dict]]:
    """(auditors, symbols) from one Financial Statement and Notes data set: one auditor row per
    firm named in an annual report, and the trading symbols each filing tags."""
    source = "sec:fsn:" + Path(path).stem
    with zipfile.ZipFile(path) as z:
        subs: dict[str, dict] = {}
        with z.open(_member(z, "sub.tsv")) as fh:
            text = io.TextIOWrapper(fh, encoding="utf-8", errors="replace", newline="")
            for r in csv.DictReader(text, delimiter="\t", quoting=csv.QUOTE_NONE):
                subs[r["adsh"]] = r
        groups: dict[tuple[str, str], dict] = {}
        symbols: dict[tuple[str, str], dict] = {}
        with z.open(_member(z, "txt.tsv")) as fh:
            text = io.TextIOWrapper(fh, encoding="utf-8", errors="replace", newline="")
            header = text.readline().rstrip("\n").split("\t")
            col = {name: i for i, name in enumerate(header)}
            for line in text:
                parts = line.split("\t", 2)
                if len(parts) < 3 or (parts[1] not in AUDITOR_TAGS and parts[1] not in SYMBOL_TAGS):
                    continue
                f = line.rstrip("\n").split("\t")
                if len(f) < len(header) or f[col["dimn"]] != "0" or f[col["coreg"]]:
                    continue  # a dimension or a co-registrant: not the registrant itself
                adsh, tag, value = f[col["adsh"]], f[col["tag"]], f[col["value"]].strip()
                key = (adsh, f[col["context"]])
                if tag in AUDITOR_TAGS:
                    g = groups.setdefault(key, {"ddate": _ymd(f[col["ddate"]])})
                    g[AUDITOR_TAGS[tag]] = value
                else:
                    symbols.setdefault(key, {"ddate": _ymd(f[col["ddate"]])})[SYMBOL_TAGS[tag]] = (
                        value
                    )
    auditors = []
    for (adsh, _), g in groups.items():
        sub = subs.get(adsh)
        if sub is None or sub.get("form", "").upper() not in ANNUAL or not g.get("name"):
            continue
        filed = _ymd(sub.get("filed"))
        if filed is None:
            continue
        fid = firm_id(g.get("firm_id"))
        auditors.append({
            "accession_number": adsh, "auditor_key": f"pcaob:{fid}" if fid else
            "name:" + " ".join(g["name"].upper().split()),
            "cik": normalize_cik(sub["cik"]), "form_type": sub["form"].upper(),
            "fiscal_year": int(sub["fy"]) if (sub.get("fy") or "").isdigit() else None,
            "period_end": _ymd(sub.get("period")), "audited_through": g.get("ddate"),
            "filed_date": filed, "auditor_name": " ".join(g["name"].split())[:300],
            "pcaob_firm_id": fid, "auditor_location": " ".join((g.get("location") or "")
                                                               .split())[:200] or None,
            "source": source,
        })  # fmt: skip
    syms = []
    for (adsh, _), g in symbols.items():
        sub = subs.get(adsh)
        if sub is None or not (g.get("symbol") or g.get("registrant")):
            continue
        registrant = " ".join((g.get("registrant") or "").split())[:300] or None
        syms.append({"accession_number": adsh, "cik": normalize_cik(sub["cik"]),
                     "form_type": sub.get("form", "").upper(), "filed_date": _ymd(sub.get("filed")),
                     "symbol": (g.get("symbol") or "").upper()[:20] or None,
                     "exchange": g.get("exchange"), "title": g.get("title"),
                     "registrant": registrant})  # fmt: skip
    # one row per filing and firm (a firm tagged in two contexts keeps the later period)
    best: dict[tuple, dict] = {}
    for a in auditors:
        k = (a["accession_number"], a["auditor_key"])
        if k not in best or (a["audited_through"] or date.min) > (
            best[k]["audited_through"] or date.min
        ):
            best[k] = a
    return list(best.values()), syms


def load(db: Session, path: str | Path) -> dict:
    rows, syms = parse_notes_zip(path)
    accs = sorted({r["accession_number"] for r in rows})
    for i in range(0, len(accs), 1000):
        db.execute(delete(CompanyAuditor).where(
            CompanyAuditor.accession_number.in_(accs[i : i + 1000])))  # fmt: skip
    for i in range(0, len(rows), 5000):
        db.execute(insert(CompanyAuditor), rows[i : i + 5000])
    db.commit()
    return {"auditor_rows": len(rows), "reports": len(accs), "symbol_rows": len(syms)}


def _current(reports: list[list[CompanyAuditor]]) -> list[CompanyAuditor]:
    """The firm that audited each report's own period, oldest report first. When the tags do
    not say (both firms on one period), the firm that continues in the next report, else the
    one new since the previous report."""
    out: list[CompanyAuditor] = []
    for i, rows in enumerate(reports):
        latest = max((r.audited_through or date.min) for r in rows)
        top = [r for r in rows if (r.audited_through or date.min) == latest]
        if len(top) > 1 and i + 1 < len(reports):
            nxt = {r.auditor_key for r in reports[i + 1]}
            top = [r for r in top if r.auditor_key in nxt] or top
        if len(top) > 1 and i > 0:
            prev = {r.auditor_key for r in reports[i - 1]}
            top = [r for r in top if r.auditor_key not in prev] or top
        out.append(sorted(top, key=lambda r: r.auditor_key)[0])
    return out


def for_company(db: Session, cik: str, as_of: date | None = None) -> dict | None:
    stmt = select(CompanyAuditor).where(CompanyAuditor.cik == cik)
    if as_of:
        stmt = stmt.where(CompanyAuditor.filed_date <= as_of)
    rows = list(db.scalars(stmt))
    if not rows:
        return None
    by_report: dict[str, list[CompanyAuditor]] = {}
    for r in rows:
        by_report.setdefault(r.accession_number, []).append(r)
    order = sorted(by_report.values(),
                   key=lambda rs: (rs[0].period_end or date.min, rs[0].filed_date))  # fmt: skip
    # an amendment re-files the same period: keep the latest report per period
    per_period: dict = {}
    for rs in order:
        per_period[rs[0].period_end or rs[0].accession_number] = rs
    reports = list(per_period.values())
    current = _current(reports)
    history: list[dict] = []
    for r in current:
        if history and history[-1]["_key"] == r.auditor_key:
            h = history[-1]
            h["to_fiscal_year"], h["reports"] = r.fiscal_year, h["reports"] + 1
            h["name"], h["location"] = r.auditor_name, r.auditor_location
        else:
            history.append({"_key": r.auditor_key, "name": r.auditor_name,
                            "pcaob_firm_id": r.pcaob_firm_id, "location": r.auditor_location,
                            "from_fiscal_year": r.fiscal_year, "to_fiscal_year": r.fiscal_year,
                            "reports": 1})  # fmt: skip
    last = current[-1]
    filings_401 = db.scalars(select(Filing).where(
        Filing.cik == cik, Filing.form_type.like("8-K%"),
        Filing.items.like(f"%{CHANGE_ITEM}%"), Filing.filing_date.is_not(None),
        *([Filing.filing_date <= as_of] if as_of else []),
    ).order_by(Filing.filing_date)).all()  # fmt: skip
    firm_changes = []
    for before, after in zip(current, current[1:], strict=False):
        if before.auditor_key == after.auditor_key:
            continue
        # the 8-K item 4.01 filed between the two annual reports, the latest one if several
        linked = [f for f in filings_401 if before.filed_date < f.filing_date <= after.filed_date]
        f401 = linked[-1] if linked else None
        firm_changes.append({
            "fiscal_year": after.fiscal_year,
            "from": {"name": before.auditor_name, "pcaob_firm_id": before.pcaob_firm_id},
            "to": {"name": after.auditor_name, "pcaob_firm_id": after.pcaob_firm_id},
            "first_report": {"form_type": after.form_type,
                             "filed_date": after.filed_date.isoformat(),
                             "accession_number": after.accession_number,
                             "source_url": filing_index_url(cik, after.accession_number)},
            "item_401": {"filing_date": f401.filing_date.isoformat(), "form_type": f401.form_type,
                         "source_url": f401.source_url} if f401 else None,
        })  # fmt: skip
    changes_q = select(Filing).where(
        Filing.cik == cik, Filing.form_type.like("8-K%"), Filing.items.like(f"%{CHANGE_ITEM}%")
    )
    if as_of:
        changes_q = changes_q.where(Filing.filing_date <= as_of)
    changes = db.scalars(changes_q.order_by(Filing.filing_date.desc()).limit(10)).all()
    for h in history:
        h.pop("_key")
    return {
        "current": {
            "name": last.auditor_name,
            "pcaob_firm_id": last.pcaob_firm_id,
            "location": last.auditor_location,
            "since_fiscal_year": history[-1]["from_fiscal_year"],
            "latest_report": {
                "form_type": last.form_type,
                "fiscal_year": last.fiscal_year,
                "period_end": last.period_end.isoformat() if last.period_end else None,
                "filed_date": last.filed_date.isoformat(),
                "accession_number": last.accession_number,
                "source_url": filing_index_url(cik, last.accession_number),
            },  # fmt: skip
        },
        "history": list(reversed(history)),
        # a change of firm between consecutive annual reports, with the 8-K 4.01 announcing it
        "firm_changes": list(reversed(firm_changes)),
        "changes": [
            {
                "filing_date": f.filing_date.isoformat() if f.filing_date else None,
                "form_type": f.form_type,
                "item": CHANGE_ITEM,
                "source_url": f.source_url,
            }
            for f in changes
        ],  # fmt: skip
        "notes": NOTES,
    }
