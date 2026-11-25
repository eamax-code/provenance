"""Insider activity by rules on Forms 4 (launch plan F-03). Information about what insiders
did, never a recommendation: the words are "activity", not "buy signals".

- sec.insider_cluster_buy: three or more insiders bought shares in the open market (code P)
  within 30 days. One event per cluster, at the filing of the third insider's purchase.
  F-03f: a purchase under an employee or director stock purchase plan, a plan trust or dividend
  reinvestment (plan_purchase) is not an open-market buy: never in a cluster or a first buy.
  F-03g: nor is a purchase likely under one though not stated (plan_inferred: a fraction of a
  share under 100 shares).
- sec.insider_first_buy: an insider's first open-market purchase at the company in two years
  or more (only where the data reaches two years back before the purchase).
- sec.insider_large_sale: an officer or director sold $1 million or more in one filing,
  and the filing says the sale was not made under a Rule 10b5-1 trading plan.

Backfill never notifies (ADR 0004): only activity found in filings first loaded in this run is
published to the feed and webhooks.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.timeutil import iso_z
from app.db.models import InsiderActivity, InsiderFiling, InsiderTransaction, utcnow
from app.services import insiders
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
# F-03b (PM, 2026-11-25) held clusters the joint-filer rule found in old filings until affiliate
# linking (F-03d) was checked; F-03d is in, so they are stored like any backfill again
HOLD_OLD_CLUSTERS = False
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


def _trades(db: Session, cik: str, amended: bool = True, plan: bool = True,
            inferred: bool = True) -> list[Trade]:  # fmt: skip
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
        if plan and r.trans_code == "P" and r.plan_purchase:
            continue  # F-03f: bought under a plan, not in the open market
        if inferred and r.trans_code == "P" and r.plan_inferred:
            continue  # F-03g: likely bought under a plan, though not stated
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


# F-03d: affiliates that file apart. Entity names: the first two significant words; generic
# words and Roman numerals do not count ("GENERAL ATLANTIC, L.P." and "GENERAL ATLANTIC GENPAR
# (BERMUDA), L.P." are one group; "ABRAMS CAPITAL" has one significant word and links only by
# filing together). An individual: only when he signs an entity's form in a control capacity, or
# a remark or footnote names him in one; never by attorney-in-fact or power of attorney (an
# issuer's secretary signs that way for every insider), never by surname alone.
_GENERIC = set("""
lp llc inc ltd co corp corporation company l p fund funds partners partner management capital
holdings holding the and of gp group trust plc sa ag nv bv sarl scsp limited lllp llp pte
""".split())  # fmt: skip
_ROMAN = re.compile(r"^(?=[ivxlc]+$)c{0,3}(xc|xl|l?x{0,3})(ix|iv|v?i{0,3})$")
_ATTORNEY = re.compile(r"attorney|\bp\.?\s?o\.?\s?a\b|by proxy|pursuant to (a )?power", re.I)
# entity forms the insider data's entity test misses ("General Atlantic GenPar (Lux) SCSp")
_MORE_ENTITY = re.compile(r"\b(?:scsp|s\.?\s?[aà]\.?\s?r\.?\s?l|sarl|fundaci[oó]n|stiftung|spa|kg"
                          r"|lllp|pte|bhd|l\.?\s?p)\b", re.I)  # fmt: skip
_CONTROL = re.compile(
    r"\b(?:managing member|general partner|sole member|managing partner|chief executive officer"
    r"|ceo|(?<!vice )(?<!vp )president|(?<!portfolio )(?<!investment )(?<!asset )manager"
    r"|principal(?! (?:financial|accounting|executive))"
    r"|controlling (?:member|shareholder|person))\b",
    re.I,
)  # fmt: skip
_NOTE_CONTROL = re.compile(r"\b(?:managing member|general partner|sole member|managing partner"
                           r"|controlling (?:member|shareholder|person)|controls)\b",
                           re.I)  # fmt: skip


_SEPARATE = re.compile(r"filing a separate form 4|file a separate form 4|separate form 4", re.I)
_SUFFIX = {"lp", "llc", "inc", "ltd", "co", "corp", "corporation", "l", "p", "plc", "limited"}


def _words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", (text or "").lower())


def _entity_words(name: str) -> list[str]:
    """An entity's name as words, without its legal-form suffix ("Ares Management LLC" is
    ["ares", "management"])."""
    w = _words(name)
    while w and w[-1] in _SUFFIX:
        w.pop()
    return w


def _contains(words: list[str], part: list[str]) -> bool:
    n = len(part)
    return any(words[i : i + n] == part for i in range(len(words) - n + 1))


def _name_key(name: str) -> tuple[str, ...] | None:
    words = [w for w in re.findall(r"[a-z0-9]+", (name or "").lower())
             if w not in _GENERIC and not _ROMAN.match(w) and not w.isdigit()
             and len(w) > 1]  # fmt: skip
    return tuple(words[:2]) if len(words) >= 2 else None


def _person_tokens(name: str) -> frozenset[str]:
    return frozenset(w for w in re.findall(r"[a-z]+", (name or "").lower()) if len(w) > 1)


def _signers(signature: str) -> list[str]:
    """Names that sign in a control capacity: "X LLC By: Nadir Ali, as General Manager" gives
    "Nadir Ali"; a signature with no capacity, or by attorney-in-fact, gives none."""
    if _ATTORNEY.search(signature):
        return []
    out = []
    for chunk in re.split(r"\bby\b:?|on behalf of", signature, flags=re.I):
        chunk = chunk.replace("/s/", " ").strip(" ,;:")
        name, _, capacity = chunk.partition(",")
        if capacity and _CONTROL.search(capacity):
            out.append(name.strip())
    return out


def affiliates(db: Session, cik: str, why: list | None = None) -> list[tuple[str, str]]:
    """F-03d: pairs of owner CIKs at this issuer to count as one buyer though they never share a
    Form 4: entities with the same name key, and an individual (himself a reporting owner here)
    with the entities of a form he signs, or that names him, in a control role."""
    from app.db.models import InsiderFilingText

    owners: dict[str, str] = {}
    by_acc: dict[str, list[str]] = {}
    for acc, owner, name in db.execute(select(InsiderFiling.accession_number,
                                              InsiderFiling.owner_cik, InsiderFiling.owner_name)
                                       .where(InsiderFiling.issuer_cik == cik)):  # fmt: skip
        owners[owner] = name
        by_acc.setdefault(acc, []).append(owner)
    entities = {c for c, n in owners.items()
                if insiders.is_entity(n) or _MORE_ENTITY.search(n or "")}  # fmt: skip
    people = {c: _person_tokens(n) for c, n in owners.items() if c not in entities}
    pairs: list[tuple[str, str]] = []
    keys: dict[tuple, str] = {}
    for c in sorted(entities):
        k = _name_key(owners[c])
        if k is not None:
            if k in keys:
                pairs.append((keys[k], c))
                if why is not None:
                    why.append({"rule": "name", "a": owners[keys[k]], "b": owners[c],
                                "evidence": " ".join(k)})  # fmt: skip
            else:
                keys[k] = c
    accs = [a for a, os_ in by_acc.items() if set(os_) & entities]
    for part in range(0, len(accs), 1000):
        for t in db.scalars(select(InsiderFilingText).where(
                InsiderFilingText.accession_number.in_(accs[part:part + 1000]))):  # fmt: skip
            ents = [o for o in by_acc[t.accession_number] if o in entities]
            named = [_person_tokens(n) for sig in json.loads(t.signatures) for n in _signers(sig)]
            texts = [x for x in [t.remarks or "", *json.loads(t.footnotes)] if x]
            sentences = [s_ for x in texts for s_ in re.split(r"(?<=[.;])\s+", x)
                         if _NOTE_CONTROL.search(s_) and not _ATTORNEY.search(s_)]  # fmt: skip
            # entity to entity: an entity owner here named in full in a control sentence, or in a
            # remark that it files a separate Form 4 for the same holding (Ares: "The sole member
            # of ASOF Investment Management is Ares Management LLC")
            linked_texts = sentences + [s_ for x in texts for s_ in re.split(r"(?<=[.;])\s+", x)
                                        if _SEPARATE.search(s_)]  # fmt: skip
            for c in entities - set(ents):
                full = _entity_words(owners[c])
                distinct = any(w not in _GENERIC and not _ROMAN.match(w) for w in full)
                if (
                    len(full) >= 2
                    and distinct
                    and any(_contains(_words(s_), full) for s_ in linked_texts)
                ):
                    pairs += [(c, e) for e in ents]
                    if why is not None:
                        why += [{"rule": "entity_note", "a": owners[c], "b": owners[e],
                                 "accession_number": t.accession_number,
                                 "evidence": next(s_ for s_ in linked_texts
                                                  if _contains(_words(s_), full))[:300]}
                                for e in ents]  # fmt: skip
            for c, toks in people.items():
                if len(toks) < 2:
                    continue
                sig = next((n for n in named if toks <= n), None)
                note = (
                    None
                    if sig
                    else next((s_ for s_ in sentences if toks <= _person_tokens(s_)), None)
                )
                if sig or note:
                    pairs += [(c, e) for e in ents]
                    if why is not None:
                        why += [{"rule": "signature" if sig else "note", "a": owners[c],
                                 "b": owners[e], "accession_number": t.accession_number,
                                 "evidence": json.loads(t.signatures) if sig else note[:300]}
                                for e in ents]  # fmt: skip
    return pairs


def buyers(trades: list[Trade], extra: list[tuple[str, str]] | None = None) -> dict[str, str]:
    """F-03b: owner CIK -> buyer. The reporting owners of one Form 4 are one buyer (a fund, its
    general partner and its managers), and so is every entity that ever files together with
    them at this issuer (one group): a cluster needs three buyers who file apart."""
    parent: dict[str, str] = {}

    def find(x: str) -> str:
        while parent.setdefault(x, x) != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(x: str, y: str) -> None:
        a, b = find(x), find(y)
        if a != b:
            parent[max(a, b)] = min(a, b)

    for t in trades:
        ciks = [o["owner_cik"] for o in t.owners]
        for c in ciks[1:]:
            union(ciks[0], c)
        for c in ciks:
            find(c)
    for x, y in extra or []:  # F-03d: affiliates that file apart
        union(x, y)
    return {c: find(c) for c in parent}


def detect(db: Session, cik: str, coverage_start: date | None = None,
           amended: bool = True, joint_as_one: bool = True,
           affiliated: bool = True, plan: bool = True,
           inferred: bool = True) -> list[dict]:  # fmt: skip
    """Every activity the rules find for one issuer, oldest first (not stored). amended=False
    reads trades as before Q-03d (each filing on its own), joint_as_one=False counts every
    reporting owner as a buyer (before F-03b), plan=False counts plan purchases as buys (before
    F-03f) and inferred=False inferred ones (before F-03g), for the corrections of stored
    events."""
    trades = _trades(db, cik, amended, plan, inferred)
    buys = [t for t in trades if t.code == "P"]
    out: list[dict] = []
    extra = affiliates(db, cik) if joint_as_one and affiliated else None
    group = buyers(trades, extra) if joint_as_one else {}

    # cluster buying: a new cluster only after 30 days without one
    last_cluster: date | None = None
    for i, t in enumerate(buys):
        window = [b for b in buys[: i + 1] if (t.trans_date - b.trans_date).days <= CLUSTER_DAYS]
        people = {group.get(o["owner_cik"], o["owner_cik"]) for b in window for o in b.owners}
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
        if HOLD_OLD_CLUSTERS and a["type"] == CLUSTER and have and not fresh:
            continue  # F-03b: clusters the joint-filer rule newly finds wait for F-03d
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
              now=None, before_rules: dict | None = None,
              reason: str | None = None, adds: bool = True) -> list[dict]:  # fmt: skip
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

    rules = before_rules if before_rules is not None else {"amended": False,
                                                            "joint_as_one": False}  # fmt: skip
    before = {(a["type"], a["trade"].accession): a
              for a in detect(db, cik, coverage_start, **rules)}  # fmt: skip
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
            if reason is not None:
                why = reason
            elif forms.get(key[1]) == "4/A":
                why = "counted twice: a Form 4/A repeating its original Form 4"
            elif key[1] not in trades:
                why = "the trade was cancelled by its Form 4/A"
            else:
                why = "no longer meets the rule once Form 4/A corrections are applied"
            actions.append({"action": "retract", "key": key, "row": r, "reason": why})
            if write:
                r.status, r.retracted_at, r.retraction_reason = "retracted", now, why
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
        elif a is not None and b is None and adds:
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
