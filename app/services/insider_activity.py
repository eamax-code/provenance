"""Insider activity by rules on Forms 4 (launch plan F-03). Information about what insiders
did, never a recommendation: the words are "activity", not "buy signals".

- sec.insider_cluster_buy: three or more insiders bought shares in the open market (code P)
  within 30 days. One event per cluster, at the filing of the third insider's purchase.
- sec.insider_first_buy: an insider's first open-market purchase at the company in two years
  or more (only where the data reaches two years back before the purchase).
- sec.insider_large_sale: an officer or director sold $1 million or more in one filing,
  and the filing says the sale was not made under a Rule 10b5-1 trading plan.

Backfill never notifies (ADR 0004): only activity found in filings first loaded in this run is
published to the feed and webhooks.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import InsiderActivity, InsiderFiling, InsiderTransaction, utcnow
from app.services.sec_client import filing_index_url

CLUSTER = "sec.insider_cluster_buy"
FIRST_BUY = "sec.insider_first_buy"
LARGE_SALE = "sec.insider_large_sale"
TYPES = {
    CLUSTER: ("Three or more insiders bought shares in the open market within 30 days",
              "Insider cluster buying"),
    FIRST_BUY: ("An insider's first open-market purchase in two years or more",
                "First buy in 2+ years"),
    LARGE_SALE: ("An officer or director sold $1 million or more, not under a 10b5-1 plan",
                 "Large insider sale"),
}  # fmt: skip
CLUSTER_DAYS = 30
CLUSTER_MIN = 3
FIRST_BUY_GAP_DAYS = 730
LARGE_SALE_USD = Decimal(1_000_000)


@dataclass
class Trade:
    accession: str
    filing_date: date
    trans_date: date
    code: str
    value: Decimal
    shares: Decimal
    owners: list[dict]
    plan_10b5_1: bool | None
    officer_or_director: bool


def _role(f: InsiderFiling) -> str:
    if f.is_officer:
        return f.officer_title or "Officer"
    if f.is_director:
        return "Director"
    if f.is_ten_percent_owner:
        return "10% owner"
    return f.other_text or "Insider"


def _trades(db: Session, cik: str) -> list[Trade]:
    filings: dict[str, list[InsiderFiling]] = {}
    for f in db.scalars(select(InsiderFiling).where(InsiderFiling.issuer_cik == cik)):
        filings.setdefault(f.accession_number, []).append(f)
    rows = db.scalars(
        select(InsiderTransaction).where(
            InsiderTransaction.issuer_cik == cik,
            InsiderTransaction.row_kind == "transaction",
            InsiderTransaction.is_derivative.is_(False),
            InsiderTransaction.trans_code.in_(("P", "S")),
            InsiderTransaction.trans_date.is_not(None),
        )
    ).all()
    by_key: dict[tuple, Trade] = {}
    for r in rows:
        owners = filings.get(r.accession_number)
        if not owners:
            continue
        key = (r.accession_number, r.trans_code)
        value = (r.shares or 0) * (r.price or 0)
        t = by_key.get(key)
        if t is None:
            t = by_key[key] = Trade(
                accession=r.accession_number, filing_date=owners[0].filing_date,
                trans_date=r.trans_date, code=r.trans_code, value=Decimal(0), shares=Decimal(0),
                owners=[{"owner_cik": o.owner_cik, "name": o.owner_name, "role": _role(o)}
                        for o in owners],
                plan_10b5_1=owners[0].plan_10b5_1,
                officer_or_director=any(o.is_officer or o.is_director for o in owners),
            )  # fmt: skip
        t.value += value
        t.shares += r.shares or 0
        t.trans_date = min(t.trans_date, r.trans_date)
    return sorted(by_key.values(), key=lambda t: (t.trans_date, t.filing_date, t.accession))


def detect(db: Session, cik: str, coverage_start: date | None = None) -> list[dict]:
    """Every activity the rules find for one issuer, oldest first (not stored)."""
    trades = _trades(db, cik)
    buys = [t for t in trades if t.code == "P"]
    out: list[dict] = []

    # cluster buying: a new cluster only after 30 days without one
    last_cluster: date | None = None
    for i, t in enumerate(buys):
        window = [b for b in buys[: i + 1] if (t.trans_date - b.trans_date).days <= CLUSTER_DAYS]
        people = {o["owner_cik"] for b in window for o in b.owners}
        if len(people) >= CLUSTER_MIN and (
            last_cluster is None or (t.trans_date - last_cluster).days > CLUSTER_DAYS
        ):
            last_cluster = t.trans_date
            owners = {o["owner_cik"]: o for b in window for o in b.owners}
            out.append({
                "type": CLUSTER, "trade": t, "owners": list(owners.values()),
                "detail": {"insiders": len(people), "days": CLUSTER_DAYS,
                           "value_usd": float(sum(b.value for b in window)),
                           "first_trade": window[0].trans_date.isoformat()},
            })  # fmt: skip

    # first purchase in two years, per owner
    start = coverage_start or (trades[0].filing_date if trades else None)
    previous: dict[str, date] = {}
    for t in buys:
        for o in t.owners:
            prior = previous.get(o["owner_cik"])
            covered = start is not None and (t.trans_date - start).days >= FIRST_BUY_GAP_DAYS
            if covered and (prior is None or (t.trans_date - prior).days >= FIRST_BUY_GAP_DAYS):
                out.append({
                    "type": FIRST_BUY, "trade": t, "owners": [o],
                    "detail": {"previous_purchase": prior.isoformat() if prior else None,
                               "value_usd": float(t.value), "shares": float(t.shares)},
                })  # fmt: skip
            previous[o["owner_cik"]] = t.trans_date

    # large sales outside a 10b5-1 plan, as the filing states
    for t in trades:
        if (t.code == "S" and t.plan_10b5_1 is False and t.officer_or_director
                and t.value >= LARGE_SALE_USD):  # fmt: skip
            out.append({
                "type": LARGE_SALE, "trade": t, "owners": t.owners,
                "detail": {"value_usd": float(t.value), "shares": float(t.shares),
                           "plan_10b5_1": False},
            })  # fmt: skip
    return sorted(out, key=lambda a: (a["trade"].trans_date, a["type"]))


def store(
    db: Session,
    cik: str,
    new_accessions: set[str] | None = None,
    coverage_start: date | None = None,
) -> list[InsiderActivity]:
    """Store what detect() finds. Activity from filings in `new_accessions` is published to the
    feed (pending); everything else is backfill and stays off it. Returns the new rows."""
    have = set(db.scalars(
        select(InsiderActivity.activity_type + "|" + InsiderActivity.accession_number)
        .where(InsiderActivity.cik == cik)
    ))  # fmt: skip
    added = []
    for a in detect(db, cik, coverage_start):
        t = a["trade"]
        if f"{a['type']}|{t.accession}" in have:
            continue
        fresh = new_accessions is not None and t.accession in new_accessions
        row = InsiderActivity(
            cik=cik, activity_type=a["type"], activity_date=t.trans_date,
            filing_date=t.filing_date, accession_number=t.accession,
            owners=json.dumps(a["owners"]), detail=json.dumps(a["detail"]),
            source_url=filing_index_url(cik, t.accession),
            stream_status="pending" if fresh else "skipped", created_at=utcnow(),
        )  # fmt: skip
        db.add(row)
        have.add(f"{a['type']}|{t.accession}")
        added.append(row)
    db.flush()
    return added


_coverage: dict[str, date | None] = {}


def coverage_start(db: Session) -> date | None:
    """The earliest Form 3/4/5 loaded: before it, "no purchase in two years" cannot be known."""
    if "start" not in _coverage:
        from sqlalchemy import func

        _coverage["start"] = db.scalar(select(func.min(InsiderFiling.filing_date)))
    return _coverage["start"]


def accessions(db: Session, cik: str) -> set[str]:
    return set(db.scalars(
        select(InsiderFiling.accession_number).where(InsiderFiling.issuer_cik == cik)
    ))  # fmt: skip


def label(row: InsiderActivity) -> str:
    owners = json.loads(row.owners)
    detail = json.loads(row.detail)
    if row.activity_type == CLUSTER:
        return f"{detail['insiders']} insiders bought shares in the open market within 30 days"
    who = owners[0]["name"] if owners else "An insider"
    role = owners[0].get("role") if owners else None
    who = f"{who} ({role})" if role else who
    if row.activity_type == FIRST_BUY:
        return f"{who} made a first open-market purchase in two years or more"
    return f"{who} sold ${detail['value_usd'] / 1e6:,.1f} million, not under a 10b5-1 plan"


def as_dict(row: InsiderActivity) -> dict:
    return {
        "type": row.activity_type, "label": label(row), "short_label": TYPES[row.activity_type][1],
        "cik": row.cik, "activity_date": row.activity_date.isoformat(),
        "filing_date": row.filing_date.isoformat(), "accession_number": row.accession_number,
        "owners": json.loads(row.owners), "detail": json.loads(row.detail),
        "filing_url": row.source_url,
    }  # fmt: skip
