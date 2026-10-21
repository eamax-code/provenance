"""Idempotent ingestion of ListingRecords into venues, instruments and lifecycle events."""

from __future__ import annotations

import json
import logging
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.logging import log_event
from app.db.models import Issuer, ListedInstrument, ListingEvent, Market, utcnow
from app.services.markets.records import (
    EVENT_DELISTING,
    EVENT_IPO,
    EVENT_MODIFIED,
    EVENT_NEW_LISTING,
    EVENT_REINSTATED,
    EVENT_SUSPENDED,
    STATUS_DELISTED,
    STATUS_LISTED,
    STATUS_SUSPENDED,
    ListingRecord,
    event_key,
    is_valid_isin,
)

logger = logging.getLogger("app.markets.ingest")

# A listing first seen with a first-trade date older than this is backfill: no event is raised.
NEW_LISTING_WINDOW_DAYS = 45


@dataclass
class MarketIngestResult:
    source: str
    records_seen: int = 0
    inserted: int = 0
    updated: int = 0
    unchanged: int = 0
    skipped: int = 0
    events: dict[str, int] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)

    def bump(self, event_type: str) -> None:
        self.events[event_type] = self.events.get(event_type, 0) + 1


def ensure_market(
    db: Session,
    mic: str,
    name: str,
    country: str,
    region: str,
    source: str,
    source_url: str,
    operating_mic: str | None = None,
) -> Market:
    market = db.scalar(select(Market).where(Market.mic == mic))
    if market is None:
        market = Market(
            mic=mic,
            operating_mic=operating_mic,
            name=name,
            country=country,
            region=region,
            source=source,
            source_url=source_url,
        )
        db.add(market)
        db.flush()
    return market


def ensure_issuer(
    db: Session,
    legal_name: str,
    lei: str | None,
    source: str,
    now: datetime,
    country: str | None = None,
    jurisdiction: str | None = None,
    registration_status: str | None = None,
    source_url: str | None = None,
) -> Issuer:
    issuer = None
    if lei:
        issuer = db.scalar(select(Issuer).where(Issuer.lei == lei))
    if issuer is None and not lei:
        issuer = db.scalar(
            select(Issuer).where(Issuer.lei.is_(None), Issuer.legal_name == legal_name)
        )
    if issuer is None:
        issuer = Issuer(
            lei=lei,
            legal_name=legal_name,
            country=country,
            jurisdiction=jurisdiction,
            registration_status=registration_status,
            source=source,
            source_url=source_url,
            first_detected_at=now,
            updated_at=now,
        )
        db.add(issuer)
        db.flush()
        return issuer
    changed = False
    for attr, value in (
        ("legal_name", legal_name),
        ("country", country),
        ("jurisdiction", jurisdiction),
        ("registration_status", registration_status),
        ("source_url", source_url),
    ):
        if value and getattr(issuer, attr) != value:
            setattr(issuer, attr, value)
            changed = True
    if changed:
        issuer.updated_at = now
        issuer.source = source
    return issuer


def ingest_records(
    db: Session,
    records: Iterable[ListingRecord],
    source: str,
    now: datetime | None = None,
    known_markets: dict[str, Market] | None = None,
) -> MarketIngestResult:
    """Upsert instruments for one source pass and raise lifecycle events. Commits at the end."""
    now = now or utcnow()
    today = now.date()
    result = MarketIngestResult(source=source)
    markets = known_markets or {m.mic: m for m in db.scalars(select(Market))}
    for rec in records:
        result.records_seen += 1
        key = rec.listing_key
        if key is None or rec.mic not in markets:
            result.skipped += 1
            continue
        if rec.isin and not is_valid_isin(rec.isin):
            rec.isin = None  # keep the row under its symbol key; never store a bad ISIN
        if not rec.issuer_name:
            rec.issuer_name = rec.short_name or rec.isin
            rec.quality_status = "partial"
            rec.notes.append("issuer name missing in source")
        issuer = ensure_issuer(db, rec.issuer_name, rec.issuer_lei, source, now)
        row = db.scalar(
            select(ListedInstrument).where(
                ListedInstrument.listing_key == key, ListedInstrument.mic == rec.mic
            )
        )
        new_hash = rec.record_hash()
        status = rec.derived_status(today)
        if row is None:
            row = ListedInstrument(
                isin=rec.isin,
                listing_key=key,
                mic=rec.mic,
                issuer_name=rec.issuer_name,
                issuer_lei=rec.issuer_lei or issuer.lei,
                symbol=rec.symbol,
                short_name=rec.short_name,
                cfi_code=rec.cfi_code,
                instrument_type=rec.instrument_type,
                currency=rec.currency,
                admission_requested_date=rec.admission_requested_date,
                admission_approved_date=rec.admission_approved_date,
                first_trade_date=rec.first_trade_date,
                termination_date=rec.termination_date,
                status=status,
                source=source,
                source_url=rec.source_url,
                source_record_hash=new_hash,
                source_published_at=rec.source_published_at,
                first_detected_at=now,
                last_seen_at=now,
                processed_at=now,
                quality_status=rec.quality_status,
            )
            db.add(row)
            db.flush()
            result.inserted += 1
            _events_for_new_row(db, row, rec, issuer, today, now, result)
            continue

        row.last_seen_at = now
        if row.source_record_hash == new_hash:
            result.unchanged += 1
            continue
        before = _snapshot(row)
        row.issuer_name = rec.issuer_name
        row.isin = rec.isin or row.isin
        row.issuer_lei = rec.issuer_lei or row.issuer_lei
        row.symbol = rec.symbol or row.symbol
        row.short_name = rec.short_name or row.short_name
        row.cfi_code = rec.cfi_code or row.cfi_code
        row.instrument_type = rec.instrument_type
        row.currency = rec.currency or row.currency
        row.admission_requested_date = rec.admission_requested_date or row.admission_requested_date
        row.admission_approved_date = rec.admission_approved_date or row.admission_approved_date
        row.first_trade_date = rec.first_trade_date or row.first_trade_date
        row.termination_date = rec.termination_date
        row.status = status
        row.source = source
        row.source_url = rec.source_url
        row.source_record_hash = new_hash
        row.source_published_at = rec.source_published_at
        row.processed_at = now
        row.quality_status = rec.quality_status
        result.updated += 1
        _events_for_change(db, row, before, rec, now, result)
    db.commit()
    log_event(
        logger,
        logging.INFO,
        "listings ingested",
        source=source,
        seen=result.records_seen,
        inserted=result.inserted,
        updated=result.updated,
        events=result.events,
    )
    return result


def _snapshot(row: ListedInstrument) -> dict:
    return {
        "issuer_name": row.issuer_name,
        "short_name": row.short_name,
        "symbol": row.symbol,
        "status": row.status,
        "termination_date": row.termination_date,
        "first_trade_date": row.first_trade_date,
    }


def _add_event(
    db: Session,
    row: ListedInstrument,
    event_type: str,
    event_date: date | None,
    now: datetime,
    result: MarketIngestResult,
    details: dict | None = None,
    quality: str = "ok",
) -> bool:
    key = event_key(row.listing_key, row.mic, event_type, event_date)
    exists = db.scalar(select(ListingEvent.id).where(ListingEvent.event_key == key))
    if exists is not None:
        return False
    db.add(
        ListingEvent(
            instrument_id=row.id,
            isin=row.isin,
            listing_key=row.listing_key,
            symbol=row.symbol,
            mic=row.mic,
            issuer_name=row.issuer_name,
            event_type=event_type,
            event_date=event_date,
            event_key=key,
            source=row.source,
            source_url=row.source_url,
            details=json.dumps(details) if details else None,
            detected_at=now,
            quality_status=quality,
        )
    )
    result.bump(event_type)
    return True


def _first_listing_for_issuer(db: Session, row: ListedInstrument) -> bool:
    stmt = select(ListedInstrument.id).where(ListedInstrument.id != row.id)
    if row.issuer_lei:
        stmt = stmt.where(ListedInstrument.issuer_lei == row.issuer_lei)
    else:
        stmt = stmt.where(ListedInstrument.issuer_name == row.issuer_name)
    return db.scalar(stmt.limit(1)) is None


def _events_for_new_row(
    db: Session,
    row: ListedInstrument,
    rec: ListingRecord,
    issuer: Issuer,
    today: date,
    now: datetime,
    result: MarketIngestResult,
) -> None:
    if rec.explicit_event == EVENT_IPO:
        _add_event(
            db,
            row,
            EVENT_IPO,
            rec.first_trade_date,
            now,
            result,
            {"stated_by_source": True},
        )
    window = timedelta(days=NEW_LISTING_WINDOW_DAYS)
    recent_start = (
        rec.first_trade_date is not None
        and today - window <= rec.first_trade_date <= today + window
    )
    if row.status == STATUS_LISTED and recent_start:
        first = _first_listing_for_issuer(db, row)
        _add_event(
            db,
            row,
            EVENT_NEW_LISTING,
            rec.first_trade_date,
            now,
            result,
            {
                "first_listing_for_issuer_in_our_data": first,
                "note": "first_listing_for_issuer_in_our_data is relative to what this service "
                "has ingested; it is not an IPO determination",
            },
        )
    elif (
        row.status == STATUS_DELISTED
        and rec.termination_date
        and today - window <= rec.termination_date
    ):
        _add_event(db, row, EVENT_DELISTING, rec.termination_date, now, result)


def _events_for_change(
    db: Session,
    row: ListedInstrument,
    before: dict,
    rec: ListingRecord,
    now: datetime,
    result: MarketIngestResult,
) -> None:
    if before["status"] != row.status:
        if row.status == STATUS_DELISTED:
            _add_event(db, row, EVENT_DELISTING, row.termination_date, now, result)
        elif row.status == STATUS_SUSPENDED:
            _add_event(db, row, EVENT_SUSPENDED, now.date(), now, result)
        elif row.status == STATUS_LISTED and before["status"] in (
            STATUS_SUSPENDED,
            STATUS_DELISTED,
        ):
            _add_event(db, row, EVENT_REINSTATED, now.date(), now, result)
    changed = {
        k: {"before": _j(before[k]), "after": _j(getattr(row, k))}
        for k in ("issuer_name", "short_name", "symbol")
        if before[k] != getattr(row, k)
    }
    if changed:
        _add_event(db, row, EVENT_MODIFIED, now.date(), now, result, changed)


def _j(value):
    return value.isoformat() if isinstance(value, date) else value


def instruments_for_issuer(db: Session, issuer: Issuer) -> list[ListedInstrument]:
    if issuer.lei:
        return list(
            db.scalars(select(ListedInstrument).where(ListedInstrument.issuer_lei == issuer.lei))
        )
    return list(
        db.scalars(
            select(ListedInstrument).where(ListedInstrument.issuer_name == issuer.legal_name)
        )
    )


def utc_today() -> date:
    return datetime.now(UTC).date()
