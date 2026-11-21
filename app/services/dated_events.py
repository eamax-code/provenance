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
LABELS = {
    LOCKUP_EXPIRY: ("An IPO lock-up ends (derived from the final prospectus)", "Lock-up ends")
}
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


def as_dict(row: DatedEvent) -> dict:
    detail = json.loads(row.detail)
    days = detail.get("lockup_days")
    return {
        "type": row.event_type,
        "label": f"The {days}-day IPO lock-up ends (derived from the final prospectus)"
        if days
        else LABELS[row.event_type][0],
        "short_label": LABELS[row.event_type][1],
        "cik": row.cik,
        "event_date": row.event_date.isoformat(),
        "accession_number": row.accession_number,
        "detail": detail,
        "filing_url": row.source_url,
    }
