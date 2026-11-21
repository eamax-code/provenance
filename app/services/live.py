"""Keyless "Live from EDGAR" lists for the home page: recent IPO milestones and notable filings.

Stored data only, never an SEC request, so the demo and anonymous visitors cannot cause load on
EDGAR. Each row links the filing on sec.gov. Cached like the rest of the public API.
"""

from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import Company, Filing, OfficerChange
from app.services import filing_events, ipo_pipeline, ipo_terms
from app.services.officer_changes import CHANGE_LABELS
from app.services.public import _now_iso, cached

MAX_LIMIT = 5
IPO_DAYS = 30
EVENT_DAYS = 14
IPO_NOTE = (
    "Stages come from EDGAR filings: a final prospectus (424B4) means the offering priced, not "
    "that shares trade. Information, not investment advice."
)
EVENT_NOTE = (
    "What each filing means comes from its form type and the 8-K items the company declared. "
    "Information, not signals or investment advice."
)
STAGE_TEXT = {
    "confidential": ("Confidential draft", "Draft registration submitted (DRS)"),
    "filed": ("Filed", "Registration statement filed"),
    "amended": ("Amended", "Registration statement amended"),
    "effective": ("Effective", "Registration declared effective"),
    "listing": ("Listing", "Exchange listing registered"),
    "priced": ("Priced", "Final prospectus filed (424B4)"),
    "withdrawn": ("Withdrawn", "Registration withdrawn"),
}


def _limit(limit: int) -> int:
    return max(1, min(MAX_LIMIT, limit))


def public_ipos(db: Session, limit: int = MAX_LIMIT, today: date | None = None) -> dict:
    limit = _limit(limit)

    def build():
        since = (today or date.today()) - timedelta(days=IPO_DAYS)
        rows = []
        # IPOs only: Form 10 registrations (funds, spin-offs) are not offerings to the public
        for item in [i for i in ipo_pipeline.companies(db, since=since) if i["kind"] == "ipo"]:
            if len(rows) == limit:
                break
            # the most recent milestone, so the date shown is the activity that put it here
            shown = {
                k: v
                for k, v in item["milestones"].items()
                if not v["form_type"].startswith("10-12")
            }
            if not shown:
                continue
            stage = max(
                shown, key=lambda s: (shown[s]["filing_date"], ipo_pipeline.STAGES.index(s))
            )
            m = item["milestones"][stage]
            if m["filing_date"] is None or m["filing_date"] < since:
                continue
            stage_label, label = STAGE_TEXT[stage]
            rows.append({
                "cik": item["cik"], "company_name": item["name"], "ticker": item["ticker"],
                "stage": stage, "stage_label": stage_label,
                "label": f"{label}" if stage != "filed" else f"{label} ({m['form_type']})",
                "date": m["filing_date"].isoformat() if m["filing_date"] else None,
                "form_type": m["form_type"], "blank_check": item["blank_check"],
                "filing_url": m["source_url"],
            })  # fmt: skip
        terms = ipo_terms.terms_by_cik(db, [r["cik"] for r in rows])
        for r in rows:
            r.update(ipo_terms.flat(terms.get(r["cik"])))
        return {"data": rows, "as_of": _now_iso(), "notes": [IPO_NOTE]}

    return cached(f"live_ipos:{limit}:{today}", build)


_ROLE_WORDS = (
    ("chief executive", "CEO"), ("chief financial", "CFO"), ("chief operating", "COO"),
    ("chief accounting", "CAO"), ("chief legal", "CLO"), ("general counsel", "General counsel"),
    ("chief technology", "CTO"), ("chair", "Chair"), ("president", "President"),
    ("director", "Director"), ("treasurer", "Treasurer"), ("secretary", "Secretary"),
)  # fmt: skip
SHORT_MAX = 24  # the home strip is one line on a phone


def _role_short(role: str | None) -> str:
    text = (role or "").lower()
    for words, short in _ROLE_WORDS:
        if words in text:
            return short
    return "Officer"


def _officer_short(c: OfficerChange) -> str:
    verb = {"departure": "departs", "retirement": "retires", "appointment": "appointed",
            "election": "elected", "role_change": "changes role",
            "not_standing_for_reelection": "leaves board"}.get(c.change_type)  # fmt: skip
    text = f"{_role_short(c.role)} {verb}" if verb else "Leadership change"
    return text if len(text) <= SHORT_MAX else "Leadership change"


EXCHANGE_FORM_25_MIN = 20  # an issuer files Form 25 once or twice; an exchange files hundreds


def _exchange_filers(db: Session) -> set[str]:
    """CIKs that file Form 25 for other companies (the exchanges themselves)."""

    def build():
        rows = db.execute(
            select(Filing.cik)
            .where(Filing.form_type.in_(("25-NSE", "25")))
            .group_by(Filing.cik)
            .having(func.count() >= EXCHANGE_FORM_25_MIN)
        )
        return {r[0] for r in rows}

    return cached("exchange_filers", build)


def event_rows(
    db: Session,
    since: date,
    limit: int,
    until: date | None = None,
    cik: str | None = None,
) -> list[dict]:
    """Notable filings filed in [since, until], newest first, one row per filing under its most
    consequential type; officer changes from 8-K item 5.02 included."""
    found: list[tuple[date, int, dict]] = []
    stmt = (
        select(Filing, Company.legal_name, Company.ticker)
        .join(Company, Company.cik == Filing.cik)
        .where(
            Filing.filing_date >= since,
            filing_events.condition(list(filing_events.FILING_EVENT_TYPES)),
        )
        .order_by(Filing.filing_date.desc(), Filing.accepted_at.desc().nulls_last())
        .limit(max(200, limit * 4))
    )
    changes_stmt = (
        select(OfficerChange, Company.legal_name, Company.ticker)
        .join(Company, Company.cik == OfficerChange.cik)
        .where(OfficerChange.filing_date >= since, OfficerChange.change_type != "compensation")
        .order_by(OfficerChange.filing_date.desc())
        .limit(max(50, limit * 2))
    )
    if until:
        stmt = stmt.where(Filing.filing_date <= until)
        changes_stmt = changes_stmt.where(OfficerChange.filing_date <= until)
    if cik:
        stmt = stmt.where(Filing.cik == cik)
        changes_stmt = changes_stmt.where(OfficerChange.cik == cik)
    exchanges = set() if cik else _exchange_filers(db)
    for f, name, ticker in db.execute(stmt).all():
        types = filing_events.types_for(f.form_type, f.items, f.event_tags)
        if not types or f.cik in exchanges:
            continue  # an exchange files Form 25 for others; the issuer's own row counts
        top = min(types, key=filing_events.PRIORITY.index)
        found.append((f.filing_date, filing_events.PRIORITY.index(top), {
            "type": top, "label": filing_events.FILING_EVENT_TYPES[top].label,
            "short_label": filing_events.SHORT_LABELS[top],
            "cik": f.cik, "company_name": name, "ticker": ticker,
            "date": f.filing_date.isoformat(), "form_type": f.form_type,
            "filing_url": f.source_url, "_accn": f.accession_number,
        }))  # fmt: skip
    for c, name, ticker in db.execute(changes_stmt).all():
        found.append((c.filing_date, filing_events.OFFICER_CHANGE_RANK, {
            "type": "sec.officer_change",
            "label": f"{c.person or 'An officer'} {CHANGE_LABELS.get(c.change_type, '')}"
                     f"{', ' + c.role if c.role else ''} (8-K item 5.02)",
            "short_label": _officer_short(c),
            "cik": c.cik, "company_name": name, "ticker": ticker,
            "date": c.filing_date.isoformat(), "form_type": "8-K",
            "filing_url": c.source_url, "_accn": c.accession_number,
        }))  # fmt: skip
    # newest first; on one day the more consequential first; one row per filing
    found.sort(key=lambda r: (-r[0].toordinal(), r[1]))
    rows, seen = [], set()
    for _, _, row in found:
        accn = row.pop("_accn")
        if accn in seen:
            continue
        seen.add(accn)
        rows.append(row)
        if len(rows) == limit:
            break
    return rows


def public_events(db: Session, limit: int = MAX_LIMIT, today: date | None = None) -> dict:
    limit = _limit(limit)

    def build():
        since = (today or date.today()) - timedelta(days=EVENT_DAYS)
        return {"data": event_rows(db, since, limit), "as_of": _now_iso(), "notes": [EVENT_NOTE]}

    return cached(f"live_events:{limit}:{today}", build)


PIPELINE_MAX = 200
LOOKBACK_DAYS = 730


def _lockup_within(terms: dict | None, today: date, days: int) -> bool:
    exp = (terms or {}).get("lockup_expiry", {}).get("value")
    return bool(exp) and today <= date.fromisoformat(exp) <= today + timedelta(days=days)


def public_pipeline(
    db: Session,
    days: int = 90,
    kind: str | None = "ipo",
    lockup_within_days: int | None = None,
    today: date | None = None,
) -> dict:
    """Companies going public by stage, with deal-term values (evidence on the per-company
    endpoint). Stored data only."""
    today = today or date.today()

    def build():
        since = today - timedelta(days=LOOKBACK_DAYS if lockup_within_days else days)
        items = ipo_pipeline.companies(db, since=since)
        if kind:
            items = [i for i in items if i["kind"] == kind]
        terms = ipo_terms.terms_by_cik(db, [i["cik"] for i in items])
        if lockup_within_days:
            items = [i for i in items if _lockup_within(terms.get(i["cik"]), today,
                                                        lockup_within_days)]  # fmt: skip
        counts = {s: 0 for s in ipo_pipeline.STAGES}
        rows = []
        for i in items:
            counts[i["stage"]] += 1
            t = terms.get(i["cik"]) or {}
            rows.append({
                **_ipo_row(i), "terms": {k: v["value"] for k, v in t.items()} or None,
                "derived_terms": sorted(k for k, v in t.items() if v.get("derived")),
            })  # fmt: skip
        return {"data": rows[:PIPELINE_MAX], "counts": counts, "total": len(rows),
                "as_of": _now_iso(), "notes": [IPO_NOTE, TERMS_NOTE]}  # fmt: skip

    return cached(f"pipeline:{days}:{kind}:{lockup_within_days}:{today}", build)


def public_ipo(db: Session, cik: str, today: date | None = None) -> dict | None:
    today = today or date.today()

    def build():
        items = [i for i in ipo_pipeline.companies(db, since=today - timedelta(days=LOOKBACK_DAYS))
                 if i["cik"] == cik]  # fmt: skip
        if not items:
            return None
        return {**_ipo_row(items[0]), "terms": ipo_terms.terms_by_cik(db, [cik]).get(cik),
                "notes": [IPO_NOTE, TERMS_NOTE]}  # fmt: skip

    return cached(f"ipo:{cik}:{today}", build)


TERMS_NOTE = (
    "Deal terms are read from the prospectus by rules; each value on the company endpoint "
    "carries the sentence it came from. Lock-up expiry and quiet period end are derived dates."
)


def _ipo_row(i: dict) -> dict:
    return {
        "cik": i["cik"], "name": i["name"], "ticker": i["ticker"], "exchange": i["exchange"],
        "kind": i["kind"], "stage": i["stage"], "blank_check": i["blank_check"],
        "last_activity": i["last_activity"].isoformat(),
        "milestones": {k: {**v, "filing_date": v["filing_date"].isoformat()
                           if v["filing_date"] else None} for k, v in i["milestones"].items()},
    }  # fmt: skip
