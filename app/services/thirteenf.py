"""Institutional ownership from Form 13F (launch plan E-1).

Source: the SEC's Form 13F data sets (one zip of tab-separated files per three months of filing
dates). Each 13F-HR lists a manager's positions at a quarter end. Rules:

- Shares only: rows reported in principal amount (PRN) and put or call options are left out.
- Values in dollars. Filings made before 2023-01-03 reported thousands; they are multiplied by
  1,000 (keyed on the filing date, as the SEC's instructions are).
- Amendments, per manager and quarter, in filing order: an original 13F-HR or a 13F-HR/A
  RESTATEMENT replaces what was there; a 13F-HR/A NEW HOLDINGS adds positions. With `as_of`,
  only filings made by that date count.
- A quarter is shown once the 45-day filing deadline has passed and the data loaded reaches it.
- Positions are joined to companies through the internal CUSIP map (app.services.cusips); a
  CUSIP is never returned.
"""

from __future__ import annotations

import csv
import io
import zipfile
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path

from sqlalchemy import delete, func, insert, select
from sqlalchemy.orm import Session

from app.db.models import Filing13F, Holding13F, JobState, utcnow
from app.services import cusips as cusip_map
from app.services.sec_client import filing_index_url, normalize_cik

DOLLARS_FROM = date(2023, 1, 3)
DEADLINE_DAYS = 45
TOP_HOLDERS = 15
LOADED_KEY = "13f:loaded_through"
HOLDINGS_FORMS = ("13F-HR", "13F-HR/A")
LAG_NOTE = "13F data lag: managers file up to 45 days after the quarter ends."
NOTES = [
    "Positions are as reported on Form 13F-HR by institutional investment managers with at "
    "least $100 million in US-listed securities; options and amounts in principal are excluded.",
    "Some managers report positions for affiliated managers, and confidential positions may be "
    "omitted, so totals are an approximation of institutional ownership.",
    "Holder changes compare each manager's latest report for the quarter with the one before; "
    "a manager that has not filed for the quarter yet is not counted as exiting.",
]

csv.field_size_limit(10_000_000)


def _date(value: str | None) -> date | None:
    v = (value or "").strip()
    for fmt in ("%d-%b-%Y", "%Y-%m-%d", "%m/%d/%Y"):  # 30-JUN-2026 (month names match any case)
        try:
            return datetime.strptime(v, fmt).date()
        except ValueError:
            continue
    return None


def _dec(value: str | None) -> Decimal | None:
    v = (value or "").strip().replace(",", "")
    if not v:
        return None
    try:
        return Decimal(v)
    except InvalidOperation:
        return None


def dollars(value: Decimal, filing_date: date) -> Decimal:
    """The reported value in dollars: thousands before 2023-01-03."""
    return value * 1000 if filing_date < DOLLARS_FROM else value


def _rows(z: zipfile.ZipFile, name: str) -> Iterator[dict]:
    member = next((n for n in z.namelist() if n.upper().endswith(name)), None)
    if member is None:
        return
    with z.open(member) as fh:
        text = io.TextIOWrapper(fh, encoding="utf-8", errors="replace", newline="")
        yield from csv.DictReader(text, delimiter="\t", quoting=csv.QUOTE_NONE)


@dataclass
class Dataset:
    filings: list[dict]
    holdings: Iterator[dict]  # streamed, one filing at a time
    classes: dict[str, str]  # cusip -> title of class, for the issuer_prefix rule (filled as read)


def _filings(z: zipfile.ZipFile, source: str) -> dict[str, dict]:
    cover = {r["ACCESSION_NUMBER"]: r for r in _rows(z, "COVERPAGE.TSV")}
    summary = {r["ACCESSION_NUMBER"]: r for r in _rows(z, "SUMMARYPAGE.TSV")}
    filings: dict[str, dict] = {}
    for r in _rows(z, "SUBMISSION.TSV"):
        acc, form = r["ACCESSION_NUMBER"].strip(), r["SUBMISSIONTYPE"].strip().upper()
        period, filed = _date(r["PERIODOFREPORT"]), _date(r["FILING_DATE"])
        cik = (r.get("CIK") or "").strip()
        if not (acc and period and filed and cik.isdigit()):
            continue
        c, s = cover.get(acc, {}), summary.get(acc, {})
        amendment = (c.get("AMENDMENTTYPE") or "").strip().upper() or None
        if form.endswith("/A") and amendment is None:
            amendment = "RESTATEMENT"  # an amendment that does not say: treated as complete
        total = _dec(s.get("TABLEVALUETOTAL"))
        entries = (s.get("TABLEENTRYTOTAL") or "").strip()
        filings[acc] = {
            "accession_number": acc, "filer_cik": normalize_cik(cik),
            "filer_name": " ".join((c.get("FILINGMANAGER_NAME") or "").split())[:300]
            or normalize_cik(cik),
            "report_period": period, "filing_date": filed, "form_type": form,
            "amendment_type": amendment if form.endswith("/A") else None,
            "report_type": (c.get("REPORTTYPE") or "").strip() or None,
            "entry_total": int(entries) if entries.isdigit() else None,
            "value_total_usd": dollars(total, filed) if total is not None else None,
            "confidential_omitted": (s.get("ISCONFIDENTIALOMITTED") or "").strip().upper() == "Y",
            "source": source,
        }  # fmt: skip
    return filings


def _holdings(z: zipfile.ZipFile, filings: dict[str, dict], classes: dict[str, str]):
    """Positions summed per filing and CUSIP. The data sets list each filing's rows together;
    a filing seen again after another one is refused rather than double counted."""
    done: set[str] = set()
    run: dict[str, dict] = {}
    run_acc = None
    for r in _rows(z, "INFOTABLE.TSV"):
        acc = r["ACCESSION_NUMBER"].strip()
        if acc != run_acc:
            yield from run.values()
            if run_acc:
                done.add(run_acc)
            if acc in done:
                raise ValueError(f"13F rows of {acc} are not listed together")
            run, run_acc = {}, acc
        f = filings.get(acc)
        if f is None or f["form_type"] not in HOLDINGS_FORMS:
            continue
        if (r.get("SSHPRNAMTTYPE") or "").strip().upper() != "SH":
            continue  # principal amounts (notes)
        if (r.get("PUTCALL") or "").strip():
            continue  # options
        cusip = (r.get("CUSIP") or "").strip().upper()
        shares, value = _dec(r.get("SSHPRNAMT")), _dec(r.get("VALUE"))
        if not cusip_map.valid(cusip) or shares is None or value is None:
            continue
        title = " ".join((r.get("TITLEOFCLASS") or "").split())[:100] or None
        if title:
            classes.setdefault(cusip, title)
        h = run.get(cusip)
        if h is None:
            run[cusip] = {
                "accession_number": acc, "cusip": cusip, "filer_cik": f["filer_cik"],
                "report_period": f["report_period"], "filing_date": f["filing_date"],
                "title_of_class": title, "shares": shares,
                "value_usd": dollars(value, f["filing_date"]),
            }  # fmt: skip
        else:
            h["shares"] += shares
            h["value_usd"] += dollars(value, f["filing_date"])
    yield from run.values()


def parse_dataset(path: str | Path, source: str | None = None) -> Dataset:
    """Read one Form 13F data set zip. Iterate `holdings` while the returned object is alive;
    the zip stays open until the iterator is exhausted."""
    source = source or "sec:13f-dataset:" + Path(path).stem
    z = zipfile.ZipFile(path)
    filings = _filings(z, source)
    classes: dict[str, str] = {}

    def stream():
        try:
            yield from _holdings(z, filings, classes)
        finally:
            z.close()

    return Dataset(list(filings.values()), stream(), classes)


def window_end(path: str | Path) -> date | None:
    """The last filing date a data set covers, from its name (01jun2026-31aug2026_form13f)."""
    stem = Path(path).stem.split("_")[0]
    try:
        return datetime.strptime(stem.split("-")[1], "%d%b%Y").date()
    except (IndexError, ValueError):
        return None


def load_dataset(db: Session, path: str | Path, batch: int = 20_000) -> dict:
    """Store one data set (idempotent per filing), extend the CUSIP map with other share
    classes, and record how far the loaded filings reach."""
    ds = parse_dataset(path)
    accs = [f["accession_number"] for f in ds.filings]
    for i in range(0, len(accs), 1000):
        chunk = accs[i : i + 1000]
        db.execute(delete(Holding13F).where(Holding13F.accession_number.in_(chunk)))
        db.execute(delete(Filing13F).where(Filing13F.accession_number.in_(chunk)))
    now = utcnow()
    for i in range(0, len(ds.filings), batch):
        db.execute(insert(Filing13F), [{**f, "created_at": now} for f in ds.filings[i : i + batch]])
    held, buf = 0, []
    for h in ds.holdings:
        buf.append(h)
        if len(buf) >= batch:
            db.execute(insert(Holding13F), buf)
            held, buf = held + len(buf), []
    if buf:
        db.execute(insert(Holding13F), buf)
        held += len(buf)
    prefixed = cusip_map.map_prefixes(db, ds.classes)
    end = window_end(path)
    if end:
        mark_loaded_through(db, end)
    db.commit()
    return {"filings": len(ds.filings), "holdings": held, "prefix_mapped": prefixed,
            "window_end": end.isoformat() if end else None}  # fmt: skip


def mark_loaded_through(db: Session, day: date) -> None:
    row = db.get(JobState, LOADED_KEY)
    if row is None:
        db.add(JobState(name=LOADED_KEY, value=day.isoformat(), updated_at=utcnow()))
    elif day.isoformat() > row.value:
        row.value, row.updated_at = day.isoformat(), utcnow()


def loaded_through(db: Session) -> date | None:
    row = db.get(JobState, LOADED_KEY)
    return date.fromisoformat(row.value) if row else None


def quarter_ends(d: date) -> date:
    """The last quarter end on or before d."""
    if d.month % 3 == 0 and (d + timedelta(days=1)).month != d.month:
        return d
    q = (d.month - 1) // 3
    if q == 0:
        return date(d.year - 1, 12, 31)
    return date(d.year, q * 3 + 1, 1) - timedelta(days=1)


def previous_quarter(q: date) -> date:
    return quarter_ends(q.replace(day=1))


def complete_quarter(anchor: date, loaded: date | None) -> date | None:
    """The latest quarter whose filing deadline has passed by anchor and that the loaded data
    reaches."""
    if loaded is None:
        return None
    limit = min(anchor, loaded)
    q = quarter_ends(limit)
    while q + timedelta(days=DEADLINE_DAYS) > limit:
        q = previous_quarter(q)
    return q


def effective_positions(
    db: Session, codes: list[str], period: date, as_of: date | None = None
) -> tuple[dict[str, dict], set[str]]:
    """({filer_cik: {shares, value_usd, by_class, filing}}, filers that filed holdings for the
    quarter) after amendment precedence, counting only filings made by as_of."""
    if not codes:
        return {}, set()
    hq = select(Holding13F).where(Holding13F.cusip.in_(codes), Holding13F.report_period == period)
    if as_of:
        hq = hq.where(Holding13F.filing_date <= as_of)
    holdings = db.scalars(hq).all()
    by_acc: dict[str, list[Holding13F]] = {}
    for h in holdings:
        by_acc.setdefault(h.accession_number, []).append(h)
    filers = {h.filer_cik for h in holdings}
    fq = select(Filing13F).where(
        Filing13F.report_period == period, Filing13F.form_type.in_(HOLDINGS_FORMS)
    )
    if as_of:
        fq = fq.where(Filing13F.filing_date <= as_of)
    all_filers: set[str] = set()
    per_filer: dict[str, list[Filing13F]] = {}
    for f in db.scalars(fq):
        all_filers.add(f.filer_cik)
        if f.filer_cik in filers:
            per_filer.setdefault(f.filer_cik, []).append(f)
    out: dict[str, dict] = {}
    for filer, fs in per_filer.items():
        fs.sort(key=lambda f: (f.filing_date, f.accession_number))
        current: list[Filing13F] = []
        for f in fs:
            if f.amendment_type == "NEW HOLDINGS":
                current.append(f)
            else:  # an original or a restatement replaces what was there
                current = [f]
        shares, value, by_class, last = Decimal(0), Decimal(0), {}, None
        for f in current:
            for h in by_acc.get(f.accession_number, []):
                shares += h.shares
                value += h.value_usd
                by_class[h.cusip] = by_class.get(h.cusip, Decimal(0)) + h.shares
                last = f
        if last is not None and shares > 0:
            out[filer] = {"shares": shares, "value_usd": value, "by_class": by_class,
                          "filing": last, "name": current[-1].filer_name}  # fmt: skip
    return out, all_filers


def _change(prev: dict | None, cur: dict | None, filed: bool) -> str | None:
    if cur and not prev:
        return "new"
    if prev and not cur:
        return "exited" if filed else None
    if not cur:
        return None
    if cur["shares"] > prev["shares"]:
        return "added"
    if cur["shares"] < prev["shares"]:
        return "reduced"
    return "unchanged"


def ownership(
    db: Session,
    cik: str,
    as_of: date | None = None,
    today: date | None = None,
    top: int = TOP_HOLDERS,
    offset: int = 0,
    shares_outstanding: dict | None = None,
    aliases: list[str] | None = None,
    changes: list[tuple[date, str]] | None = None,
) -> dict | None:
    """The overview "ownership" block for one company, or None without 13F data for it.
    `shares_outstanding` is the cover-page figure ({value, as_of_date, source_url, ...}).
    `aliases` are the CUSIPs of a registrant linked by a holding company reorganisation (K-05, a
    1:1 exchange): the same shares, counted as one class with the company's own."""
    anchor = as_of or today or date.today()
    classes = cusip_map.cusips_for(db, cik)
    own = [c.cusip for c in classes]
    aliases = [a for a in (aliases or []) if a not in own]
    codes = own + aliases
    q = complete_quarter(anchor, loaded_through(db))
    if not codes or q is None:
        return None
    pq = previous_quarter(q)
    cur, filed_now = effective_positions(db, codes, q, as_of)
    prev, _ = effective_positions(db, codes, pq, as_of)
    if not cur:
        return None
    # one class: the company's single CUSIP, with its reorganisation twin when there is one
    single = len(own) <= 1 and len(aliases) <= 1
    held = sum((p["shares"] for p in cur.values()), Decimal(0))
    out_value = (shares_outstanding or {}).get("value")
    pct = None
    if single and out_value:
        pct = round(float(held) / float(out_value) * 100, 1)
    # holders_count_change == new - exited - not_filed (new includes managers that filed no 13F
    # for the previous quarter; not_filed are last quarter's holders with no 13F yet this quarter)
    flows = {"new": 0, "added": 0, "reduced": 0, "exited": 0, "not_filed": 0}
    for filer in set(cur) | set(prev):
        ch = _change(prev.get(filer), cur.get(filer), filer in filed_now)
        if ch in flows:
            flows[ch] += 1
        elif ch is None and filer in prev and filer not in cur:
            flows["not_filed"] += 1
    filed_through = db.scalar(
        select(func.max(Filing13F.filing_date)).where(
            Filing13F.report_period == q,
            Filing13F.form_type.in_(HOLDINGS_FORMS),
            *([Filing13F.filing_date <= as_of] if as_of else []),
        )
    )
    ranked = sorted(cur.items(), key=lambda kv: (-kv[1]["value_usd"], kv[0]))
    holders = []
    for filer, p in ranked[offset : offset + top]:
        before = prev.get(filer)
        diff = p["shares"] - before["shares"] if before else None
        holders.append({
            "filer_cik": filer,
            "name": p["name"],
            "value_usd": float(p["value_usd"]),
            "shares": float(p["shares"]) if single else None,
            "pct_of_outstanding": round(float(p["shares"]) / float(out_value) * 100, 2)
            if single and out_value else None,
            "change": _change(before, p, True),
            "shares_change": float(diff) if single and diff is not None else None,
            "shares_change_pct": round(float(diff) / float(before["shares"]) * 100, 1)
            if single and diff is not None and before["shares"] else None,
            "filing_date": p["filing"].filing_date.isoformat(),
            "form_type": p["filing"].form_type,
            "accession_number": p["filing"].accession_number,
            "filing_url": filing_index_url(filer, p["filing"].accession_number),
        })  # fmt: skip
    notes = list(NOTES)
    if aliases and any(c in aliases for p in cur.values() for c in p["by_class"]):
        notes.append("Includes holdings reported under the share identifier of the registrant "
                     "this company replaced or was replaced by in a holding company "
                     "reorganisation (the same shares, exchanged one for one).")  # fmt: skip
    if not single:
        notes.append(
            "This company has several share classes; shares are not added across classes, so "
            "shares held and the institutional percentage are not given."
        )
    if pct is not None and pct > 100:
        notes.append(
            "Above 100%: managers can report the same shares (lent, or held for affiliated "
            "managers), so the sum can exceed shares outstanding."
        )
    return {
        "quarter": q.isoformat(),
        "previous_quarter": pq.isoformat(),
        "filed_through": filed_through.isoformat() if filed_through else None,
        "lag_note": LAG_NOTE,
        "holders_count": len(cur),
        "holders_count_change": len(cur) - len(prev) if prev else None,
        "value_usd": float(sum((p["value_usd"] for p in cur.values()), Decimal(0))),
        "shares_held": float(held) if single else None,
        "shares_outstanding": shares_outstanding if out_value else None,
        "institutional_pct": pct,
        "institutional_pct_derived": {
            "formula": "13F shares held / cover-page shares outstanding",
            "inputs": [
                {"name": "shares_held", "value": float(held), "quarter": q.isoformat()},
                {
                    "name": "shares_outstanding",
                    "value": float(out_value),
                    "as_of_date": shares_outstanding.get("as_of_date"),
                    "source_url": shares_outstanding.get("source_url"),
                },
            ],
        }
        if pct is not None
        else None,  # fmt: skip
        "flows": flows,
        "flows_note": flows_note(q, changes or []),
        "top_holders": holders,
        "has_more": len(ranked) > offset + top,
        "notes": notes,
    }


def for_company(
    db: Session,
    company,
    as_of: date | None = None,
    top: int = TOP_HOLDERS,
    offset: int = 0,
    today: date | None = None,
) -> dict | None:
    """ownership() with the cover-page shares outstanding as known on as_of."""
    from app.services import cover

    so = cover.cover(db, company, as_of).get("shares_outstanding")
    return ownership(
        db, company.cik, as_of=as_of, today=today, top=top, offset=offset, shares_outstanding=so,
        aliases=reorganisation_aliases(db, company.cik),
        changes=reorganisation_changes(db, company.cik),
    )  # fmt: skip


def flows_note(quarter: date, changes: list[tuple[date, str]]) -> str | None:
    """A factual note when a quarter spans a change of share identifier (a holding company
    reorganisation): the change falls in the quarter or in its 45-day filing window."""
    for day, form in changes:
        if previous_quarter(quarter) < day <= quarter + timedelta(days=DEADLINE_DAYS):
            return (f"This quarter spans the change of share identifier on "
                    f"{day.day} {day:%b %Y} ({form}). Holder changes may reflect how managers "
                    "reported the change; compare with care.")  # fmt: skip
    return None


def reorganisation_changes(db: Session, cik: str) -> list[tuple[date, str]]:
    from app.db.models import RegistrantSuccession

    rs = RegistrantSuccession
    rows = db.scalars(select(rs).where(
        (rs.predecessor_cik == cik) | (rs.successor_cik == cik),
        rs.match_method == "holding_company_reorganization",
    ))  # fmt: skip
    return [(r.effective_date, r.evidence_form) for r in rows]


def reorganisation_aliases(db: Session, cik: str) -> list[str]:
    """CUSIPs of the predecessor or successor in a holding company reorganisation (1:1), never of
    a merger counterpart (accounting_predecessor), whose exchange ratio differs."""
    from app.db.models import RegistrantSuccession

    links = db.scalars(select(RegistrantSuccession).where(
        (RegistrantSuccession.predecessor_cik == cik) | (RegistrantSuccession.successor_cik == cik),
        RegistrantSuccession.match_method == "holding_company_reorganization",
    )).all()  # fmt: skip
    out: list[str] = []
    for link in links:
        other = link.successor_cik if link.predecessor_cik == cik else link.predecessor_cik
        out += [c.cusip for c in cusip_map.cusips_for(db, other)]
    return out
