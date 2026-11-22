"""Events that happen on a date (launch plan F-02): an IPO's lock-up ending, derived from the
final prospectus. Emitted on the day by the hourly filings tracker; past dates found the first
time are backfill and never notify (ADR 0004)."""

from __future__ import annotations

import json
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import DatedEvent, IpoTerms, utcnow

LOCKUP_EXPIRY = "sec.lockup_expiry"
# E-3: a change of audit firm seen in the annual reports' auditor tags. The 8-K item 4.01 that
# announces a change is its own event (sec.auditor_change, D-05); when one is linked, this event
# records the link and never alerts again for the same change.
AUDITOR_CHANGE = "sec.auditor_change.annual_report"
AUDITOR_WATERMARK = "auditor_change:notify_since"
LABELS = {
    LOCKUP_EXPIRY: ("An IPO lock-up ends (derived from the final prospectus)", "Lock-up ends"),
    AUDITOR_CHANGE: ("A new audit firm signs the annual report (from its auditor tags)",
                     "Auditor change (annual)"),
}  # fmt: skip
FRESH_DAYS = 1  # a date reached today or yesterday is news; older ones are backfill


def emit_due(db: Session, today: date | None = None) -> list[DatedEvent]:
    """Create the events whose date has come. Returns the new rows (published ones pending)."""
    today = today or date.today()
    have = set(db.scalars(select(DatedEvent.accession_number).where(
        DatedEvent.event_type == LOCKUP_EXPIRY)))  # fmt: skip
    added = []
    for t in db.scalars(select(IpoTerms).where(IpoTerms.form_type == "424B4")):
        if t.accession_number in have:
            continue
        terms = json.loads(t.terms)
        exp = terms.get("lockup_expiry", {}).get("value")
        if not exp or date.fromisoformat(exp) > today:
            continue
        day = date.fromisoformat(exp)
        row = DatedEvent(
            cik=t.cik, event_type=LOCKUP_EXPIRY, event_date=day,
            accession_number=t.accession_number,
            detail=json.dumps({
                "lockup_days": terms.get("lockup_days", {}).get("value"),
                "lockup_days_max": terms.get("lockup_days_max", {}).get("value"),
                "prospectus_date": t.filing_date.isoformat() if t.filing_date else None,
                "derived": True,
                "evidence": terms.get("lockup_days", {}).get("evidence"),
            }),
            source_url=t.source_url,
            stream_status="pending" if day >= today - timedelta(days=FRESH_DAYS) else "skipped",
            created_at=utcnow(),
        )  # fmt: skip
        db.add(row)
        added.append(row)
    db.flush()
    return added


def emit_auditor_changes(db: Session, today: date | None = None) -> list[DatedEvent]:
    """One event per change of audit firm between consecutive annual reports. It alerts only
    when the new firm's first report was filed after the previous run (the watermark) and no
    8-K item 4.01 already announced it; the first run is backfill and never alerts (ADR 0004)."""
    from app.db.models import CompanyAuditor, JobState
    from app.services import auditors

    today = today or date.today()
    mark = db.get(JobState, AUDITOR_WATERMARK)
    since = date.fromisoformat(mark.value) if mark else None
    have = set(db.scalars(select(DatedEvent.accession_number).where(
        DatedEvent.event_type == AUDITOR_CHANGE)))  # fmt: skip
    added = []
    for cik in db.scalars(select(CompanyAuditor.cik).distinct()):
        block = auditors.for_company(db, cik)
        for c in (block or {}).get("firm_changes", []):
            report = c["first_report"]
            if report["accession_number"] in have:
                continue
            filed = date.fromisoformat(report["filed_date"])
            fresh = since is not None and filed > since
            row = DatedEvent(
                cik=cik, event_type=AUDITOR_CHANGE, event_date=filed,
                accession_number=report["accession_number"],
                detail=json.dumps({"fiscal_year": c["fiscal_year"], "from": c["from"],
                                   "to": c["to"], "item_401": c["item_401"],
                                   "alerted_by_401": c["item_401"] is not None}),
                source_url=report["source_url"],
                stream_status="pending" if fresh and c["item_401"] is None else "skipped",
                created_at=utcnow(),
            )  # fmt: skip
            db.add(row)
            added.append(row)
    if mark is None:
        db.add(JobState(name=AUDITOR_WATERMARK, value=today.isoformat(), updated_at=utcnow()))
    else:
        mark.value, mark.updated_at = today.isoformat(), utcnow()
    db.flush()
    return added


def as_dict(row: DatedEvent) -> dict:
    detail = json.loads(row.detail)
    days = detail.get("lockup_days")
    label = LABELS[row.event_type][0]
    if row.event_type == AUDITOR_CHANGE:
        label = (f"{detail['to']['name']} replaces {detail['from']['name']} as auditor "
                 f"(fiscal year {detail['fiscal_year']}, annual report)")  # fmt: skip
    elif days:
        label = f"The {days}-day IPO lock-up ends (derived from the final prospectus)"
    return {
        "type": row.event_type,
        "label": label,
        "short_label": LABELS[row.event_type][1],
        "linked_event": {"type": "sec.auditor_change", **detail["item_401"]}
        if row.event_type == AUDITOR_CHANGE and detail.get("item_401")
        else None,
        "cik": row.cik,
        "event_date": row.event_date.isoformat(),
        "accession_number": row.accession_number,
        "detail": detail,
        "filing_url": row.source_url,
    }
