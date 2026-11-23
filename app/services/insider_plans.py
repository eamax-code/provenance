"""Trading plans (D-11) and proposed sales (D-12) for one company
(docs/contracts/insider-plans.md). Built from stored data only. Information, not signals."""

from __future__ import annotations

import json
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import DatedEvent, Filing, TradingPlan, utcnow
from app.services import dated_events
from app.services.sec_client import filing_index_url

DISCLAIMER = "Information, not signals. Not investment advice."
PLAN_ADOPTED = dated_events.PLAN_ADOPTED
PLAN_TERMINATED = dated_events.PLAN_TERMINATED
PLAN_NOTES = [
    "Trading plans are as tagged under Item 408(a) of Regulation S-K in the company's 10-Q and "
    "10-K (the SEC's Financial Statement and Notes data sets); a date the filing gives only in "
    "words is shown as written.",
]
DEFAULT_YEARS = 2
FRESH_DAYS = 1  # a filing from today or yesterday is news; older ones are backfill


def _urls(db: Session, accs: set[str]) -> dict[str, str]:
    if not accs:
        return {}
    return dict(db.execute(select(Filing.accession_number, Filing.source_url)
                           .where(Filing.accession_number.in_(sorted(accs)))).all())  # fmt: skip


def _num(v):
    if v is None:
        return None
    f = float(v)
    return int(f) if f.is_integer() else f


def plan_dict(r: TradingPlan, url: str) -> dict:
    return {
        "person_name": r.person_name, "title": r.title, "action": r.action,
        "plan_type": r.plan_type,
        "date": r.plan_date.isoformat() if r.plan_date else None,
        "date_as_written": r.plan_date_text,
        "original_adoption_date": r.original_adoption_date.isoformat()
        if r.original_adoption_date else None,
        "duration_days": r.duration_days,
        "expiration_date": r.expiration_date.isoformat() if r.expiration_date else None,
        "shares": _num(r.shares),
        "filing": {"accession_number": r.accession_number, "form": r.form_type,
                   "period": r.period.isoformat() if r.period else None,
                   "filed_date": r.filing_date.isoformat(), "source_url": url},
    }  # fmt: skip


def plans(db: Session, cik: str, since: date, as_of: date | None, limit: int) -> list[dict]:
    q = select(TradingPlan).where(TradingPlan.cik == cik, TradingPlan.filing_date >= since)
    if as_of:
        q = q.where(TradingPlan.filing_date <= as_of)
    rows = list(
        db.scalars(
            q.order_by(
                TradingPlan.filing_date.desc(),
                TradingPlan.plan_date.desc().nulls_last(),
                TradingPlan.person_name,
                TradingPlan.action,
            ).limit(limit)
        )
    )
    urls = _urls(db, {r.accession_number for r in rows})
    return [
        plan_dict(r, urls.get(r.accession_number) or filing_index_url(r.cik, r.accession_number))
        for r in rows
    ]


def for_company(db: Session, cik: str, since: date | None = None, as_of: date | None = None,
                limit: int = 50, today: date | None = None) -> dict:  # fmt: skip
    ref = as_of or today or date.today()
    since = since or ref.replace(year=ref.year - DEFAULT_YEARS)
    from app.services import form144

    return {
        "cik": cik, "as_of": as_of.isoformat() if as_of else None, "since": since.isoformat(),
        "plans": plans(db, cik, since, as_of, limit),
        "proposed_sales": form144.for_company(db, cik, since, as_of, limit),
        "labels": {"disclaimer": DISCLAIMER},
        "notes": PLAN_NOTES + form144.NOTES,
    }  # fmt: skip


# -- events -------------------------------------------------------------------------------


def emit_plan_events(db: Session, today: date | None = None) -> list[DatedEvent]:
    """One event per filing and action (adopted, terminated), dated by the filing date and
    listing the people. A filing from before yesterday is backfill and never notifies."""
    today = today or date.today()
    have = set(db.execute(select(DatedEvent.event_type, DatedEvent.accession_number).where(
        DatedEvent.event_type.in_([PLAN_ADOPTED, PLAN_TERMINATED]))).all())  # fmt: skip
    groups: dict[tuple[str, str], list[TradingPlan]] = {}
    for r in db.scalars(select(TradingPlan).order_by(TradingPlan.person_name)):
        etype = PLAN_ADOPTED if r.action == "adopted" else PLAN_TERMINATED
        if (etype, r.accession_number) not in have:
            groups.setdefault((etype, r.accession_number), []).append(r)
    urls = _urls(db, {a for _, a in groups})
    added = []
    for (etype, acc), rows in groups.items():
        first = rows[0]
        url = urls.get(acc) or filing_index_url(first.cik, acc)
        people = [{"name": r.person_name, "title": r.title, "plan_type": r.plan_type,
                   "date": r.plan_date.isoformat() if r.plan_date else r.plan_date_text}
                  for r in rows]  # fmt: skip
        row = DatedEvent(
            cik=first.cik, event_type=etype, event_date=first.filing_date, accession_number=acc,
            detail=json.dumps({"form": first.form_type, "people": people}), source_url=url,
            stream_status="pending" if first.filing_date >= today - timedelta(days=FRESH_DAYS)
            else "skipped",
            created_at=utcnow(),
        )  # fmt: skip
        db.add(row)
        added.append(row)
    db.flush()
    return added


def event_title(etype: str, detail: dict) -> str:
    people = detail.get("people") or []
    verb = "adopted" if etype == PLAN_ADOPTED else "terminated"
    if len(people) == 1 and people[0].get("name"):
        return f"{people[0]['name']} {verb} a trading plan"
    return f"{len(people)} insiders {verb} trading plans"
