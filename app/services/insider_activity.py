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

from app.core.timeutil import iso_z
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
    form: str = "4"
    period: date | None = None
    lines: int = 0


def _role(f: InsiderFiling) -> str:
    if f.is_officer:
        return f.officer_title or "Officer"
    if f.is_director:
        return "Director"
    if f.is_ten_percent_owner:
        return "10% owner"
    return f.other_text or "Insider"


def _trades(db: Session, cik: str, amended: bool = True) -> list[Trade]:
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
                form=owners[0].form_type, period=owners[0].period_of_report,
            )  # fmt: skip
        t.value += value
        t.shares += r.shares or 0
        t.lines += 1
        t.trans_date = min(t.trans_date, r.trans_date)
    trades = list(by_key.values())
    return sorted(_amended(trades) if amended else trades,
                  key=lambda t: (t.trans_date, t.filing_date, t.accession))  # fmt: skip


def _amended(trades: list[Trade]) -> list[Trade]:
    """Q-03d for the activity rules: a Form 4/A paired with an original Form 4 (same code and
    period, a reporting owner in common, filed on or after it) never counts on its own. The
    latest such 4/A restates the original when it has at least as many lines and pairs with no
    other original: its figures count, and a 4/A of 0 shares cancels the trade ("No such sale
    has occurred"), so a cancelled purchase is never one of a cluster's buyers. A partial or
    ambiguous 4/A leaves the original as filed; a 4/A with no stored original still counts."""
    amends = [t for t in trades if t.form == "4/A"]
    if not amends:
        return trades
    owners = {id(t): {o["owner_cik"] for o in t.owners} for t in trades}
    pick: dict[int, Trade] = {}
    paired: set[int] = set()
    for t in trades:
        if t.form != "4" or t.period is None:
            continue
        cands = [a for a in amends if a.code == t.code and a.period == t.period
                 and a.filing_date >= t.filing_date and owners[id(a)] & owners[id(t)]]  # fmt: skip
        paired.update(id(a) for a in cands)
        if cands:
            pick[id(t)] = max(cands, key=lambda a: (a.filing_date, a.accession))
    uses: dict[int, int] = {}
    for a in pick.values():
        uses[id(a)] = uses.get(id(a), 0) + 1
    out = []
    for t in trades:
        if t.form == "4/A" and id(t) in paired:
            continue
        a = pick.get(id(t))
        if a is not None and uses[id(a)] == 1 and a.lines >= t.lines:
            if not a.shares:
                continue  # cancelled by its 4/A
            # a 4/A can add reporting owners (a fund's general partners): they bought too
            t.owners = t.owners + [o for o in a.owners if o["owner_cik"] not in owners[id(t)]]
            # the 4/A's figures; the event keeps citing the original (stored events stay put)
            t.value, t.shares, t.trans_date = a.value, a.shares, a.trans_date
        out.append(t)
    return out


def detect(db: Session, cik: str, coverage_start: date | None = None,
           amended: bool = True) -> list[dict]:  # fmt: skip
    """Every activity the rules find for one issuer, oldest first (not stored). amended=False
    reads trades as before Q-03d (each filing on its own), for F-03c's correction."""
    trades = _trades(db, cik, amended)
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
    from app.services.chat_intents import filed_owner_name

    who = filed_owner_name(owners[0]["name"]) if owners else "An insider"
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
        # F-03c: a retracted event says why; a corrected one what it said before
        "status": row.status or "active",
        **({"retracted_at": iso_z(row.retracted_at), "retraction_reason": row.retraction_reason}
           if row.status == "retracted" else {}),
        **({"corrected_at": iso_z(row.corrected_at),
            "previous_values": json.loads(row.previous_values)} if row.corrected_at else {}),
    }  # fmt: skip


def reconcile(db: Session, cik: str, coverage_start: date | None = None, write: bool = False,
              now=None) -> list[dict]:  # fmt: skip
    """F-03c: correct one issuer's stored events for 049fef3 (the rules read trades as amended
    by their Forms 4/A), as a correction and only where that change moves the result: the
    rules are run both ways and only their differences act on stored events. An event no longer
    found is retracted (status, retracted_at, a reason), never deleted; one found with another
    date, value or owners is corrected in place, keeping what it said before in
    previous_values; one found for the first time is added as backfill (skipped, never
    notified). Returns the actions; writes them only with write=True."""
    now = now or utcnow()

    def view(a: dict) -> dict:
        return {"activity_date": a["trade"].trans_date.isoformat(), "owners": a["owners"],
                "detail": a["detail"]}  # fmt: skip

    before = {(a["type"], a["trade"].accession): a
              for a in detect(db, cik, coverage_start, amended=False)}  # fmt: skip
    after = {(a["type"], a["trade"].accession): a for a in detect(db, cik, coverage_start)}
    rows = db.scalars(select(InsiderActivity).where(InsiderActivity.cik == cik))
    have = {(r.activity_type, r.accession_number): r for r in rows}
    trades = {t.accession for t in _trades(db, cik)}
    forms = dict(db.execute(select(InsiderFiling.accession_number, InsiderFiling.form_type)
                            .where(InsiderFiling.issuer_cik == cik)).all())  # fmt: skip
    actions: list[dict] = []
    for key in sorted(set(before) | set(after)):
        b, a, r = before.get(key), after.get(key), have.get(key)
        if b is not None and a is None:
            if r is None or r.status == "retracted":
                continue
            if forms.get(key[1]) == "4/A":
                reason = "counted twice: a Form 4/A repeating its original Form 4"
            elif key[1] not in trades:
                reason = "the trade was cancelled by its Form 4/A"
            else:
                reason = "no longer meets the rule once Form 4/A corrections are applied"
            actions.append({"action": "retract", "key": key, "row": r, "reason": reason})
            if write:
                r.status, r.retracted_at, r.retraction_reason = "retracted", now, reason
        elif a is not None and r is not None:
            old = {"activity_date": r.activity_date.isoformat(), "owners": json.loads(r.owners),
                   "detail": json.loads(r.detail)}  # fmt: skip
            new = view(a)
            if (b is None or view(b) != new) and old != new:
                actions.append({"action": "update", "key": key, "row": r, "old": old, "new": new})
                if write:
                    r.previous_values, r.corrected_at = json.dumps(old), now
                    t = a["trade"]
                    r.activity_date, r.owners, r.detail = t.trans_date, \
                        json.dumps(a["owners"]), json.dumps(a["detail"])  # fmt: skip
                    r.status, r.retracted_at, r.retraction_reason = "active", None, None
        elif a is not None and b is None:
            t = a["trade"]
            actions.append({"action": "add", "key": key, "new": view(a)})
            if write:
                db.add(InsiderActivity(
                    cik=cik, activity_type=key[0], activity_date=t.trans_date,
                    filing_date=t.filing_date, accession_number=t.accession,
                    owners=json.dumps(a["owners"]), detail=json.dumps(a["detail"]),
                    source_url=filing_index_url(cik, t.accession), stream_status="skipped",
                    created_at=now,
                ))  # fmt: skip
    if write:
        db.flush()
    return actions
