"""Q-06: the SEC's fails-to-deliver per company (docs/contracts/fails-to-deliver.md).

The SEC's half-month files (cnsfails{YYYYMM}{a|b}.zip, pipe-delimited: SETTLEMENT DATE, CUSIP,
SYMBOL, QUANTITY (FAILS), DESCRIPTION, PRICE) are read through SecClient, and a row is kept when
its CUSIP is mapped to a company here (issuer_cusips, internal only: the CUSIP is never returned).
quantity is the aggregate net balance of shares failed to deliver outstanding in NSCC's CNS on that
settlement date (cumulative, not the day's new fails); price is the previous day's close as filed
("." is null). Information, not signals. Not investment advice.
"""

from __future__ import annotations

import io
import re
import zipfile
from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path

from sqlalchemy import delete, func, insert, select
from sqlalchemy.orm import Session

from app.db.models import FailsToDeliver, FtdFile, IssuerCusip
from app.services.notes import dev

PAGE = "https://www.sec.gov/data-research/sec-markets-data/fails-deliver-data"
BASE = "https://www.sec.gov"
NAME = re.compile(r"cnsfails(\d{6})([ab]?)\.zip$")
START = "200907"  # the half-month files (PM, 2026-11-25)
NOTES = [
    "Information, not signals. Not investment advice.",
    "Fails-to-deliver are not necessarily the result of short selling, and are not evidence of "
    "abusive short selling or naked short selling (the SEC's words).",
    "quantity: the balance of shares that had failed to settle and were still outstanding on that "
    "settlement date, across all clearing members (NSCC), as the SEC publishes it. It is a running "
    "balance, not the day's new fails, and it does not show how old the fails are.",
    "A date with no row had no fails balance, or its file is not yet published.",
    dev(
        "price: the previous day's close as filed; value is derived (the balance times the price)."
    ),
]


def discover(page_html: str) -> dict[str, str]:
    """{file name: URL} of every half-month file from July 2009, from the SEC page."""
    out = {}
    for href in re.findall(r'href="([^"]*cnsfails\d{6}[ab]?\.zip)"', page_html):
        name = href.rsplit("/", 1)[-1]
        m = NAME.match(name)
        if m and m.group(1) >= START:
            out[name] = href if href.startswith("http") else BASE + href
    return dict(sorted(out.items()))


def parse(data: bytes) -> list[dict]:
    """The file's rows: settlement_date, cusip, symbol, quantity, description, price (None for
    "." or unparseable). The header and any line without a date and quantity are skipped."""
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        text = zf.read(zf.namelist()[0]).decode("latin-1").replace("\x00", "")  # stray NULs
    rows = []
    for line in text.splitlines():
        parts = line.split("|")
        if len(parts) < 6 or not parts[0].strip().isdigit():
            continue
        price = parts[-1].strip()
        try:
            px = Decimal(price) if price not in ("", ".") else None
        except InvalidOperation:
            px = None
        try:
            qty = int(parts[3].strip())
            day = datetime.strptime(parts[0].strip(), "%Y%m%d").date()
        except ValueError:
            continue
        rows.append({"settlement_date": day, "cusip": parts[1].strip().upper()[:9],
                     "symbol": parts[2].strip() or None, "quantity": qty,
                     "description": "|".join(parts[4:-1]).strip() or None,
                     "price": px})  # fmt: skip
    return rows


def store(db: Session, name: str, rows: list[dict], published: date, write: bool = True) -> dict:
    """Keep the rows whose CUSIP is mapped to a company; record the file. Returns counts."""
    cusips = {r["cusip"] for r in rows}
    mapped = dict(db.execute(select(IssuerCusip.cusip, IssuerCusip.cik)).all())  # about 7,300
    keep = [{**r, "cik": mapped[r["cusip"]], "source_file": name}
            for r in rows if r["cusip"] in mapped]  # fmt: skip
    days = [r["settlement_date"] for r in rows]
    stats = {"file": name, "rows": len(rows), "matched": len(keep),
             "unmatched_cusips": len(cusips - set(mapped)),
             "unmatched_sample": sorted(cusips - set(mapped))[:3],
             "first_date": min(days).isoformat() if days else None,
             "last_date": max(days).isoformat() if days else None}  # fmt: skip
    if not write:
        return stats
    # a settlement date is in one file only: the file's rows are replaced as a whole
    db.execute(delete(FailsToDeliver).where(FailsToDeliver.source_file == name))
    for i in range(0, len(keep), 5000):
        db.execute(insert(FailsToDeliver), keep[i : i + 5000])
    db.merge(FtdFile(name=name, published=published, first_date=min(days) if days else None,
                     last_date=max(days) if days else None, rows=len(rows), matched=len(keep),
                     loaded_at=datetime.now(UTC)))  # fmt: skip
    return stats


def build(db: Session, cik: str, since: date | None = None, until: date | None = None,
          as_of: date | None = None) -> dict:  # fmt: skip
    """The response for one company: one sub-table per symbol and share class (CUSIP, never
    returned), rows by settlement date, never summed across classes."""
    files = {f.name: f for f in db.scalars(select(FtdFile))}
    known = {n for n, f in files.items() if as_of is None or f.published <= as_of}
    latest = db.scalar(select(func.max(FailsToDeliver.settlement_date))
                       .where(FailsToDeliver.cik == cik))  # fmt: skip
    until = until or (min(latest, as_of) if latest and as_of else latest or as_of or date.today())
    since = since or until - timedelta(days=180)
    q = (select(FailsToDeliver).where(FailsToDeliver.cik == cik,
                                      FailsToDeliver.settlement_date >= since,
                                      FailsToDeliver.settlement_date <= until)
         .order_by(FailsToDeliver.settlement_date))  # fmt: skip
    classes = dict(db.execute(select(IssuerCusip.cusip, IssuerCusip.class_title)
                              .where(IssuerCusip.cik == cik)).all())  # fmt: skip
    groups: dict[str, dict] = {}
    rows_by: dict[str, list] = defaultdict(list)
    for r in db.scalars(q):
        if r.source_file not in known:
            continue  # not yet published as of that date
        g = groups.setdefault(r.cusip, {"symbol": r.symbol, "class_label": classes.get(r.cusip),
                                        "description": r.description})  # fmt: skip
        g["symbol"], g["description"] = r.symbol or g["symbol"], r.description or g["description"]
        f = files[r.source_file]
        price = float(r.price) if r.price is not None else None
        rows_by[r.cusip].append({
            "settlement_date": r.settlement_date.isoformat(), "quantity": r.quantity,
            "price": price,
            "value": None if price is None else {"value": round(r.quantity * price, 2),
                                                  "derived": True, "basis": "quantity x price"},
            "source": {"file": r.source_file, "published": f.published.isoformat()},
        })  # fmt: skip
    data = [{**groups[c], "rows": rows_by[c]}
            for c in sorted(groups, key=lambda c: (groups[c]["symbol"] or "", c))]  # fmt: skip
    loaded = [f for n, f in files.items() if n in known]
    latest_file = max(loaded, key=lambda f: f.name).name if loaded else None
    coverage = {"from": min((f.first_date for f in loaded if f.first_date), default=None),
                "through": max((f.last_date for f in loaded if f.last_date), default=None),
                "latest_file": latest_file}  # fmt: skip
    coverage = {k: v.isoformat() if isinstance(v, date) else v for k, v in coverage.items()}
    notes = list(NOTES)
    if not data and not classes:
        notes.append("No CUSIP of this company is known here, so its fails cannot be matched.")
    return {"cik": cik, "since": since.isoformat(), "until": until.isoformat(), "data": data,
            "coverage": coverage, "notes": notes}  # fmt: skip


def fetch(sec, name: str, url: str, folder: Path) -> tuple[bytes, date]:
    """Download one file through SecClient (cached, fair-access) and its publication date: the
    file's Last-Modified at the SEC, else today."""
    folder.mkdir(parents=True, exist_ok=True)
    got = sec.download_file(url, folder / name)
    lm = got.get("last_modified")
    return Path(got["path"]).read_bytes(), (lm.date() if lm else date.today())


def load_new(db: Session, sec, folder: Path, reload: bool = False, limit: int | None = None,
             write: bool = True, on_file=None) -> dict:  # fmt: skip
    """Every file from July 2009 not loaded yet (all with reload), through SecClient; each file
    committed on its own, so a run stopped midway resumes. Returns counts."""
    files = discover(sec.get_text(PAGE).data)
    have = set(db.scalars(select(FtdFile.name)))
    todo = [n for n in files if reload or n not in have][:limit]
    stats = {"files_listed": len(files), "files_to_load": len(todo), "rows": 0, "matched": 0}
    for name in todo:
        data, published = fetch(sec, name, files[name], folder)
        got = store(db, name, parse(data), published, write=write)
        if write:
            db.commit()
        stats["rows"] += got["rows"]
        stats["matched"] += got["matched"]
        if on_file:
            on_file({**got, "published": published.isoformat()})
    return stats
