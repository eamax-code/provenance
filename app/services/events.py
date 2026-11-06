"""Event feed (ADR 0007): new SEC filings, officer changes read from 8-K item 5.02, and listing
events in one ordered, resumable stream.

Ingestion marks new rows `stream_status=pending` and, after its transaction commits, stamps them
`published` with `stream_at` in a short separate transaction (`publish_pending`). Readers order by
(stream_at, kind, id) and only see rows older than a settle delay, so a reader never moves past a
publication time whose rows are not yet visible. Ordering by detection time would not be safe:
a long ingestion stamps detection at its start and commits minutes later.
"""

from __future__ import annotations

import base64
import binascii
import json
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from sqlalchemy import and_, or_, select, update
from sqlalchemy.orm import Session

from app.core.timeutil import iso_z
from app.db.models import Company, Filing, ListingEvent, OfficerChange, utcnow
from app.services.form8k import split_items
from app.services.notifications import EVENT_TYPE as FILING_EVENT_TYPE

KINDS = ("filing", "leadership", "listing")  # feed order breaks ties in this (alphabetical) order
OFFICER_CHANGE_EVENT_TYPE = "sec.officer_change"
_MAX_UUID = uuid.UUID(int=(1 << 128) - 1)


@dataclass(frozen=True, order=True)
class Cursor:
    """Position in the feed. Ordering matches the feed order: (stream_at, kind, id)."""

    at: datetime
    kind: str
    id: uuid.UUID

    def encode(self) -> str:
        raw = f"{self.at.astimezone(UTC).isoformat()}|{self.kind}|{self.id.hex}"
        return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")

    @classmethod
    def decode(cls, value: str) -> Cursor:
        try:
            padded = value + "=" * (-len(value) % 4)
            at, kind, ident = base64.urlsafe_b64decode(padded.encode()).decode().split("|")
            parsed = datetime.fromisoformat(at)
            if parsed.tzinfo is None or kind not in ("", *KINDS, "~"):
                raise ValueError
            return cls(parsed.astimezone(UTC), kind, uuid.UUID(hex=ident))
        except (ValueError, UnicodeDecodeError, binascii.Error) as exc:
            raise ValueError("invalid cursor") from exc

    @classmethod
    def start(cls, at: datetime) -> Cursor:
        """Before every event published at `at` or later."""
        return cls(at, "", uuid.UUID(int=0))

    @classmethod
    def end(cls, at: datetime) -> Cursor:
        """After every event published at `at` or earlier."""
        return cls(at, "~", _MAX_UUID)


@dataclass
class EventFilters:
    kinds: tuple[str, ...] = KINDS
    ciks: list[str] = field(default_factory=list)
    form_types: list[str] = field(default_factory=list)
    items: list[str] = field(default_factory=list)  # 8-K item codes, e.g. 5.02
    mics: list[str] = field(default_factory=list)
    event_types: list[str] = field(default_factory=list)


@dataclass
class Page:
    events: list[dict]
    cursor: Cursor
    has_more: bool


def publish_pending(db: Session, now: datetime | None = None) -> int:
    """Stamp committed pending rows as published. Call after the ingesting transaction commits."""
    now = now or utcnow()
    total = 0
    for model in (Filing, OfficerChange, ListingEvent):
        result = db.execute(
            update(model)
            .where(model.stream_status == "pending")
            .values(stream_status="published", stream_at=now)
            .execution_options(synchronize_session=False)
        )
        total += result.rowcount or 0
    db.commit()
    return total


def settled_until(settle_seconds: float, now: datetime | None = None) -> datetime:
    return (now or utcnow()) - timedelta(seconds=settle_seconds)


def _after(at_col, id_col, kind: str, c: Cursor):
    if kind < c.kind:
        return at_col > c.at
    if kind == c.kind:
        return or_(at_col > c.at, and_(at_col == c.at, id_col > c.id))
    return at_col >= c.at


def fetch_page(
    db: Session, after: Cursor, until: datetime, filters: EventFilters, limit: int
) -> Page:
    """Events strictly after `after` and published at or before `until`, in feed order."""
    candidates: list[tuple[Cursor, dict]] = []
    if "filing" in filters.kinds:
        stmt = (
            select(Filing, Company.legal_name, Company.ticker)
            .join(Company, Company.cik == Filing.cik)
            .where(
                Filing.stream_status == "published",
                Filing.stream_at <= until,
                _after(Filing.stream_at, Filing.id, "filing", after),
            )
            .order_by(Filing.stream_at, Filing.id)
            .limit(limit + 1)
        )
        if filters.ciks:
            stmt = stmt.where(Filing.cik.in_(filters.ciks))
        if filters.form_types:
            stmt = stmt.where(Filing.form_type.in_(filters.form_types))
        if filters.items:
            stmt = stmt.where(or_(*(Filing.items.like(f"%{code}%") for code in filters.items)))
        for filing, name, ticker in db.execute(stmt):
            pos = Cursor(filing.stream_at, "filing", filing.id)
            candidates.append((pos, _filing_event(pos, filing, name, ticker)))
    if "leadership" in filters.kinds:
        stmt = (
            select(OfficerChange, Company.legal_name, Company.ticker)
            .join(Company, Company.cik == OfficerChange.cik)
            .where(
                OfficerChange.stream_status == "published",
                OfficerChange.stream_at.is_not(None),
                OfficerChange.stream_at <= until,
                _after(OfficerChange.stream_at, OfficerChange.id, "leadership", after),
            )
            .order_by(OfficerChange.stream_at, OfficerChange.id)
            .limit(limit + 1)
        )
        if filters.ciks:
            stmt = stmt.where(OfficerChange.cik.in_(filters.ciks))
        for change, name, ticker in db.execute(stmt):
            pos = Cursor(change.stream_at, "leadership", change.id)
            candidates.append((pos, _officer_event(pos, change, name, ticker)))
    if "listing" in filters.kinds:
        stmt = (
            select(ListingEvent)
            .where(
                ListingEvent.stream_status == "published",
                ListingEvent.stream_at <= until,
                _after(ListingEvent.stream_at, ListingEvent.id, "listing", after),
            )
            .order_by(ListingEvent.stream_at, ListingEvent.id)
            .limit(limit + 1)
        )
        if filters.mics:
            stmt = stmt.where(ListingEvent.mic.in_(filters.mics))
        if filters.event_types:
            stmt = stmt.where(ListingEvent.event_type.in_(filters.event_types))
        for ev in db.scalars(stmt):
            pos = Cursor(ev.stream_at, "listing", ev.id)
            candidates.append((pos, _listing_event(pos, ev)))
    candidates.sort(key=lambda item: item[0])
    page = candidates[:limit]
    has_more = len(candidates) > limit
    if page:
        cursor = page[-1][0]
    else:
        cursor = after
    if not has_more:
        # Everything published up to `until` has been read; later polls start from there.
        cursor = max(cursor, Cursor.end(until))
    return Page(events=[e for _, e in page], cursor=cursor, has_more=has_more)


def _filing_event(pos: Cursor, f: Filing, name: str, ticker: str | None) -> dict:
    return {
        "id": pos.encode(),
        "type": FILING_EVENT_TYPE,
        "kind": "filing",
        "stream_at": iso_z(f.stream_at),
        "data": {
            "cik": f.cik,
            "company_name": name,
            "ticker": ticker,
            "accession_number": f.accession_number,
            "form_type": f.form_type,
            "filing_date": f.filing_date.isoformat() if f.filing_date else None,
            "report_date": f.report_date.isoformat() if f.report_date else None,
            "accepted_at": iso_z(f.accepted_at),
            "items": split_items(f.items),
            "source_url": f.source_url,
        },
    }


def _officer_event(pos: Cursor, c: OfficerChange, name: str, ticker: str | None) -> dict:
    from app.services.officer_changes import change_dict

    return {
        "id": pos.encode(),
        "type": OFFICER_CHANGE_EVENT_TYPE,
        "kind": "leadership",
        "stream_at": iso_z(c.stream_at),
        "data": {
            "cik": c.cik,
            "company_name": name,
            "ticker": ticker,
            "accession_number": c.accession_number,
            "filing_date": c.filing_date.isoformat() if c.filing_date else None,
            **change_dict(c),
            "source_url": c.source_url,
        },
    }


def _listing_event(pos: Cursor, e: ListingEvent) -> dict:
    details = None
    if e.details:
        try:
            details = json.loads(e.details)
        except ValueError:
            details = None
    return {
        "id": pos.encode(),
        "type": f"listing.{e.event_type}",
        "kind": "listing",
        "stream_at": iso_z(e.stream_at),
        "data": {
            "isin": e.isin,
            "listing_key": e.listing_key,
            "symbol": e.symbol,
            "mic": e.mic,
            "issuer_name": e.issuer_name,
            "event_type": e.event_type,
            "event_date": e.event_date.isoformat() if e.event_date else None,
            "detected_at": iso_z(e.detected_at),
            "source": e.source,
            "details": details,
            "quality_status": e.quality_status,
        },
    }
