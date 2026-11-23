"""A company's events on one timeline (X-05, docs/api-contracts-explorer.md): filings, 8-K item
events, officer changes, auditor changes, IPO milestones, insider activity signals and 13F
quarter changes. Built from stored data only (no SEC fetch on read). Each item links its filing;
a 13F quarter points to /ownership, which lists every holder's filing.

With as_of only what was filed by that date counts; a derived future date (a lock-up end) is
marked upcoming. Information, not signals.
"""

from __future__ import annotations

import base64
import json
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Company, DatedEvent, Filing, InsiderActivity, OfficerChange
from app.services import (
    dated_events,
    filing_events,
    form144,
    form_names,
    insider_activity,
    insider_plans,
    tenk_sections,
)
from app.services.form8k import split_items

TYPES = ("filing", "8k_item", "officer_change", "auditor_change", "ipo", "insider", "13f_quarter",
         "trading_plan", "proposed_sale")
NOTES = ["Information, not signals. Not investment advice."]
DEFAULT_YEARS = 5
UPCOMING_DAYS = 400  # how far ahead a derived date (a lock-up end) is shown
QUARTERS = 8  # 13F quarters at most (the loaded 13F data sets reach back about a year)
# Form 25 / 25-NSE (2026-11-23): an exchange often removes one class (notes) while the common
# stock stays listed, so the label never says the company was delisted. Until the security is
# read from the filing, the honest fallback:
FORM_25 = "Form 25: a security removed from listing"
OWN_TYPES = {"sec.auditor_change": "auditor_change", "sec.ipo_priced": "ipo"}


def _item(cik, d, kind, ident, title, *, event_type=None, filing=None, url=None, details=None,
          upcoming=False) -> dict:  # fmt: skip
    return {
        "id": f"tl_{kind}_{ident}", "date": d.isoformat(), "type": kind,
        "event_type": event_type, "title": title,
        "form_type": filing.form_type if filing is not None else None,
        "accession_number": filing.accession_number if filing is not None else None,
        "filing_url": url if url is not None else (filing.source_url if filing is not None
                                                   else None),
        "upcoming": upcoming, "details": details or {},
    }  # fmt: skip


def _event_title(event_type: str) -> str:
    if event_type == "sec.delisting":
        return FORM_25
    return filing_events.FILING_EVENT_TYPES[event_type].label


def _filings(db, cik, start, end, ref, kinds, need: int | None = None) -> list[dict]:
    """need: the caller reads at most this many items. With "filing" asked every filing gives an
    item, so only the newest `need` filings are read, plus every filing on the boundary date (the
    order is date, then id). Without it, only filings carrying an asked event type are read. A
    frequent filer (JPMorgan: 28,000 filings in three years) is no longer read whole."""
    out = []
    where = [Filing.cik == cik, Filing.filing_date >= start, Filing.filing_date <= min(end, ref)]
    if "filing" not in kinds:
        wanted = [t for t, spec in filing_events.FILING_EVENT_TYPES.items()
                  if OWN_TYPES.get(t, "8k_item" if spec.item else None) in kinds]  # fmt: skip
        if not wanted:
            return out
        where.append(filing_events.condition(wanted))
    elif need is not None:
        boundary = db.scalar(
            select(Filing.filing_date).where(*where)
            .order_by(Filing.filing_date.desc()).offset(need - 1).limit(1)
        )  # fmt: skip
        if boundary is not None:
            where.append(Filing.filing_date >= boundary)
    rows = list(db.scalars(select(Filing).where(*where)))
    read_144 = set()
    if "proposed_sale" in kinds:
        accs = [f.accession_number for f in rows if f.form_type in ("144", "144/A")]
        if accs:
            from app.db.models import Form144Notice

            read_144 = set(db.scalars(select(Form144Notice.accession_number)
                                      .where(Form144Notice.accession_number.in_(accs))))
    for f in rows:
        if f.accession_number in read_144:
            continue  # shown as its proposed-sale item, with the person and the shares
        types = filing_events.types_for(f.form_type, f.items, f.event_tags)
        form_events = [t for t in types if filing_events.FILING_EVENT_TYPES[t].item is None]
        if "filing" in kinds:
            top = form_events[0] if form_events else None
            title = _event_title(top) if top else form_names.form_label(f.form_type)
            out.append(_item(cik, f.filing_date, "filing", f.accession_number, title,
                             event_type=top, filing=f,
                             details={"form_type": f.form_type, "items": split_items(f.items),
                                      "report_date": f.report_date.isoformat()
                                      if f.report_date else None}))  # fmt: skip
        for t in types:
            spec = filing_events.FILING_EVENT_TYPES[t]
            kind = OWN_TYPES.get(t, "8k_item" if spec.item else None)
            if kind is None or kind not in kinds:
                continue
            details = {"item": spec.item} if spec.item else {}
            if kind == "auditor_change":
                details = {"source": "8-K 4.01", "item": spec.item}
            if kind == "ipo":
                details = {"stage": "priced"}
            out.append(_item(cik, f.filing_date, kind, f"{f.accession_number}_{t}",
                             _event_title(t), event_type=t, filing=f, details=details))  # fmt: skip
    # X-14: an annual report says whether "what changed" can be shown for it
    annual = [i for i in out if i["type"] == "filing" and i["form_type"] in tenk_sections.FORMS]
    if annual:
        ok = tenk_sections.available(db, [i["accession_number"] for i in annual])
        for i in annual:
            i["changes_available"] = i["accession_number"] in ok
    return out


def _officer_changes(db, cik, start, end, ref) -> list[dict]:
    from app.services.officer_changes import describe

    out = []
    rows = db.scalars(
        select(OfficerChange).where(
            OfficerChange.cik == cik,
            OfficerChange.filing_date >= start,
            OfficerChange.filing_date <= min(end, ref),
        )  # fmt: skip
    )
    for c in rows:
        out.append(_item(cik, c.filing_date, "officer_change", f"{c.accession_number}_{c.seq}",
                         describe(c), event_type="sec.officer_change", url=c.source_url,
                         details={"person": c.person, "role": c.role, "change": c.change_type,
                                  "effective_date": c.effective, "verified": c.verified})
                    | {"accession_number": c.accession_number, "form_type": "8-K"})  # fmt: skip
    return out


def _dated(db, cik, start, end, ref, kinds) -> list[dict]:
    """Annual-report auditor changes and IPO lock-up ends (derived from the prospectus)."""
    out = []
    filed = {}
    q = select(DatedEvent).where(
        DatedEvent.cik == cik,
        DatedEvent.event_type.in_([dated_events.AUDITOR_CHANGE, dated_events.LOCKUP_EXPIRY]),
        DatedEvent.event_date >= start,
        DatedEvent.event_date <= max(end, ref + timedelta(days=UPCOMING_DAYS)),
    )
    events = list(db.scalars(q))
    if events:
        accs = [e.accession_number for e in events]
        filed = dict(db.execute(select(Filing.accession_number, Filing.filing_date)
                                .where(Filing.accession_number.in_(accs))).all())  # fmt: skip
    for e in events:
        source_date = filed.get(e.accession_number)
        if source_date is None or source_date > ref:
            continue  # its source filing came later than as_of: not known yet
        detail = json.loads(e.detail)
        if e.event_type == dated_events.AUDITOR_CHANGE and "auditor_change" in kinds:
            if e.event_date > min(end, ref):
                continue
            out.append(_item(cik, e.event_date, "auditor_change", f"{e.accession_number}_annual",
                             "A new audit firm signs the annual report",
                             event_type=e.event_type, url=e.source_url,
                             details={"source": "annual report tags",
                                      "from_firm": detail.get("from_firm") or detail.get("from"),
                                      "to_firm": detail.get("to_firm") or detail.get("to")})
                        | {"accession_number": e.accession_number})  # fmt: skip
        if e.event_type == dated_events.LOCKUP_EXPIRY and "ipo" in kinds:
            upcoming = e.event_date > ref
            out.append(_item(cik, e.event_date, "ipo", f"{e.accession_number}_lockup",
                             "IPO lock-up ends (derived from the final prospectus)",
                             event_type=e.event_type, url=e.source_url, upcoming=upcoming,
                             details={"stage": "lockup_expiry", "derived": True, **detail})
                        | {"accession_number": e.accession_number})  # fmt: skip
    return out


def _insider(db, cik, start, end, ref) -> list[dict]:
    out = []
    rows = db.scalars(
        select(InsiderActivity).where(
            InsiderActivity.cik == cik,
            InsiderActivity.filing_date >= start,
            InsiderActivity.filing_date <= min(end, ref),
        )  # fmt: skip
    )
    for r in rows:
        d = insider_activity.as_dict(r)
        out.append(_item(cik, r.filing_date, "insider", r.accession_number, d["label"],
                         event_type=r.activity_type, url=r.source_url,
                         details={"signal": r.activity_type.removeprefix("sec.insider_"),
                                  "owners": d["owners"], **d["detail"]})
                    | {"accession_number": r.accession_number, "form_type": "4"})  # fmt: skip
    return out


def _plans_and_sales(db, cik, start, end, ref, kinds) -> list[dict]:
    """Trading plans adopted or terminated (D-11, one item per filing and action) and Form 144
    notices (D-12), dated by their filing."""
    wanted = []
    if "trading_plan" in kinds:
        wanted += [insider_plans.PLAN_ADOPTED, insider_plans.PLAN_TERMINATED]
    if "proposed_sale" in kinds:
        wanted.append(form144.PROPOSED_SALE)
    out = []
    rows = db.scalars(select(DatedEvent).where(
        DatedEvent.cik == cik, DatedEvent.event_type.in_(wanted),
        DatedEvent.event_date >= start, DatedEvent.event_date <= min(end, ref)))  # fmt: skip
    for e in rows:
        d = json.loads(e.detail)
        if e.event_type == form144.PROPOSED_SALE:
            shares = d.get("shares")
            title = (f"Form 144: {d.get('person_name') or 'an insider'} proposes to sell "
                     + (f"{shares:,} shares" if isinstance(shares, int | float) else "shares"))
            out.append(_item(cik, e.event_date, "proposed_sale", e.accession_number, title,
                             event_type=e.event_type, url=e.source_url, details=d)
                       | {"accession_number": e.accession_number, "form_type": "144"})
        else:
            out.append(_item(cik, e.event_date, "trading_plan",
                             f"{e.accession_number}_{e.event_type.rsplit('_', 1)[-1]}",
                             insider_plans.event_title(e.event_type, d), event_type=e.event_type,
                             url=e.source_url, details=d)
                       | {"accession_number": e.accession_number, "form_type": d.get("form")})
    return out


def _thirteenf(db, company, start, end, ref) -> list[dict]:
    from app.services import thirteenf

    loaded = thirteenf.loaded_through(db)
    if loaded is None:
        return []
    out, seen = [], set()
    aliases = thirteenf.reorganisation_aliases(db, company.cik)
    q = thirteenf.complete_quarter(min(end, ref), loaded)
    for _ in range(QUARTERS):
        if q is None or q in seen:
            break
        seen.add(q)
        deadline = q + timedelta(days=45)
        if deadline < start:
            break
        block = thirteenf.ownership(
            db, company.cik, today=deadline + timedelta(days=1), top=1, aliases=aliases
        )
        if block is None or block["quarter"] != q.isoformat():
            break
        out.append(_item(company.cik, deadline, "13f_quarter", q.isoformat(),
                         f"13F holders for the quarter ended {q.isoformat()}: "
                         f"{block['holders_count']:,} managers",
                         details={"quarter": q.isoformat(),
                                  "holders_count": block["holders_count"],
                                  "holders_change": block["holders_count_change"],
                                  "flows": block["flows"]}))  # fmt: skip
        q = thirteenf.previous_quarter(q)
    return out


def build(db: Session, company: Company, kinds: tuple[str, ...] = TYPES,
          start: date | None = None, end: date | None = None, as_of: date | None = None,
          today: date | None = None, need: int | None = None) -> list[dict]:  # fmt: skip
    """Every item, newest first (date, then id). With need, the first `need` items are exact
    and later ones may be missing (callers page with offset + limit + 1)."""
    ref = as_of or today or date.today()
    end = end or ref
    start = start or ref.replace(year=ref.year - DEFAULT_YEARS)
    items = _filings(db, company.cik, start, end, ref, kinds, need)
    if "officer_change" in kinds:
        items += _officer_changes(db, company.cik, start, end, ref)
    if {"auditor_change", "ipo"} & set(kinds):
        items += _dated(db, company.cik, start, end, ref, kinds)
    if "insider" in kinds:
        items += _insider(db, company.cik, start, end, ref)
    if "13f_quarter" in kinds:
        items += _thirteenf(db, company, start, end, ref)
    if {"trading_plan", "proposed_sale"} & set(kinds):
        items += _plans_and_sales(db, company.cik, start, end, ref, kinds)
    items.sort(key=lambda i: (i["date"], i["id"]), reverse=True)
    return items


def encode_cursor(offset: int) -> str:
    return base64.urlsafe_b64encode(f"o:{offset}".encode()).decode().rstrip("=")


def decode_cursor(cursor: str | None) -> int:
    if not cursor:
        return 0
    raw = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)).decode()
    if not raw.startswith("o:") or not raw[2:].isdigit():
        raise ValueError("bad cursor")
    return int(raw[2:])
