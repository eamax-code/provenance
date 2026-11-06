"""Notifications: idempotent event creation and signed, SSRF-guarded delivery.

Two kinds share one delivery table and one worker: new SEC filings for company watches, and
listing events (new listing, delisting, suspension, ...) for listing watches scoped to a venue,
a country or a region (ticket 09)."""

from __future__ import annotations

import hashlib
import json
import logging
import random
import time
import uuid
from datetime import datetime, timedelta

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.logging import log_event
from app.core.security import derive_watch_secret, sign_webhook
from app.core.ssrf import UnsafeDestination, resolve_and_check
from app.core.timeutil import iso_z
from app.db.models import (
    CompanyWatch,
    Filing,
    ListingEvent,
    ListingWatch,
    Market,
    NotificationDelivery,
    utcnow,
)

logger = logging.getLogger("app.notifications")

EVENT_TYPE = "sec.filing.detected"
LISTING_EVENT_PREFIX = "listing."  # listing.new_listing, listing.delisting, ...
RETRYABLE_STATUSES = {408, 429, 500, 502, 503, 504}


def make_event_id(watch_id: uuid.UUID, cik: str, accession_number: str) -> str:
    digest = hashlib.sha256(f"{watch_id}|{cik}|{accession_number}".encode()).hexdigest()
    return f"evt_{digest[:32]}"


def create_deliveries_for_filing(db: Session, filing: Filing, now: datetime | None = None) -> int:
    """Create one pending delivery per active watch on the filing's CIK. Idempotent."""
    now = now or utcnow()
    watches = db.scalars(
        select(CompanyWatch).where(CompanyWatch.cik == filing.cik, CompanyWatch.is_active.is_(True))
    ).all()
    if not watches:
        return 0
    event_ids = [make_event_id(w.id, filing.cik, filing.accession_number) for w in watches]
    existing = set(
        db.scalars(
            select(NotificationDelivery.event_id).where(
                NotificationDelivery.event_id.in_(event_ids)
            )
        )
    )
    created = 0
    for watch, event_id in zip(watches, event_ids, strict=True):
        if event_id in existing:
            continue
        db.add(
            NotificationDelivery(
                watch_id=watch.id,
                filing_id=filing.id,
                event_id=event_id,
                status="pending",
                attempt_count=0,
                next_attempt_at=now,
                created_at=now,
            )
        )
        created += 1
    db.flush()
    return created


def make_listing_event_id(watch_id: uuid.UUID, event_key: str) -> str:
    digest = hashlib.sha256(f"{watch_id}|listing|{event_key}".encode()).hexdigest()
    return f"evt_{digest[:32]}"


def listing_watch_matches(watch: ListingWatch, event: ListingEvent, market: Market | None) -> bool:
    if event.event_type not in watch.event_types.split(","):
        return False
    if watch.scope_type == "mic":
        return event.mic == watch.scope_value
    if market is None:
        return False
    if watch.scope_type == "country":
        return market.country == watch.scope_value
    return market.region == watch.scope_value


def create_deliveries_for_listing_events(
    db: Session, events: list[ListingEvent], now: datetime | None = None
) -> int:
    """One pending delivery per active listing watch whose scope and event types match each
    event. Idempotent: an event reaches a watch at most once."""
    now = now or utcnow()
    watches = db.scalars(select(ListingWatch).where(ListingWatch.is_active.is_(True))).all()
    if not watches or not events:
        return 0
    db.flush()  # the events need ids
    markets = {m.mic: m for m in db.scalars(select(Market))}
    created = 0
    for event in events:
        for watch in watches:
            if not listing_watch_matches(watch, event, markets.get(event.mic)):
                continue
            event_id = make_listing_event_id(watch.id, event.event_key)
            if db.scalar(
                select(NotificationDelivery.id).where(NotificationDelivery.event_id == event_id)
            ):
                continue
            db.add(
                NotificationDelivery(
                    listing_watch_id=watch.id,
                    listing_event_id=event.id,
                    event_id=event_id,
                    status="pending",
                    attempt_count=0,
                    next_attempt_at=now,
                    created_at=now,
                )
            )
            created += 1
    db.flush()
    return created


def build_listing_payload(
    delivery: NotificationDelivery, event: ListingEvent, market: Market | None, created_at
) -> dict:
    details = json.loads(event.details) if event.details else None
    return {
        "event_id": delivery.event_id,
        "event_type": LISTING_EVENT_PREFIX + event.event_type,
        "created_at": iso_z(created_at),
        "data": {
            "event_type": event.event_type,
            "event_date": event.event_date.isoformat() if event.event_date else None,
            "isin": event.isin,
            "listing_key": event.listing_key,
            "symbol": event.symbol,
            "mic": event.mic,
            "venue": market.name if market else None,
            "country": market.country if market else None,
            "region": market.region if market else None,
            "issuer_name": event.issuer_name,
            "details": details,
            "source": event.source,
            "detected_at": iso_z(event.detected_at),
        },
    }


def build_event_payload(
    delivery: NotificationDelivery, filing: Filing, created_at: datetime
) -> dict:
    return {
        "event_id": delivery.event_id,
        "event_type": EVENT_TYPE,
        "created_at": iso_z(created_at),
        "data": {
            "cik": filing.cik,
            "accession_number": filing.accession_number,
            "form_type": filing.form_type,
            "filing_date": filing.filing_date.isoformat() if filing.filing_date else None,
            "accepted_at": iso_z(filing.accepted_at),
            "source_url": filing.source_url,
        },
    }


def encode_payload(payload: dict) -> bytes:
    return json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")


def backoff_seconds(attempt: int, base: float, rng=random.random) -> float:
    """Exponential backoff with full jitter, capped at one hour."""
    cap = min(3600.0, base * (2 ** max(0, attempt - 1)))
    return cap * (0.5 + 0.5 * rng())


class WebhookSender:
    def __init__(self, settings: Settings, http: httpx.Client | None = None) -> None:
        self.settings = settings
        self.http = http or httpx.Client(
            timeout=httpx.Timeout(settings.webhook_timeout_seconds, connect=3.0),
            follow_redirects=False,
            headers={"User-Agent": f"{settings.app_name}/{settings.app_version} webhooks"},
        )

    def send(self, url: str, body: bytes, headers: dict[str, str]) -> httpx.Response:
        resolve_and_check(url, allow_private=self.settings.webhook_allow_private_destinations)
        return self.http.post(url, content=body, headers=headers)


def deliver_pending(
    db: Session,
    settings: Settings,
    sender: WebhookSender | None = None,
    now: datetime | None = None,
    limit: int = 100,
) -> dict:
    """Process due deliveries once. Returns counts. Safe to run repeatedly."""
    now = now or utcnow()
    sender = sender or WebhookSender(settings)
    due = db.scalars(
        select(NotificationDelivery)
        .where(
            NotificationDelivery.status.in_(["pending", "retrying"]),
            NotificationDelivery.next_attempt_at <= now,
        )
        .order_by(NotificationDelivery.next_attempt_at)
        .limit(limit)
    ).all()
    counts = {"attempted": 0, "delivered": 0, "retrying": 0, "failed": 0}
    for delivery in due:
        watch, payload, missing = _target(db, delivery, now)
        if missing:
            _finalize(delivery, "failed", None, missing, now)
            counts["failed"] += 1
            continue
        if not watch.is_active:
            _finalize(delivery, "failed", None, "watch deactivated before delivery", now)
            counts["failed"] += 1
            continue
        counts["attempted"] += 1
        delivery.attempt_count += 1
        if watch.destination_type == "webhook":
            outcome, status_code, error = _attempt_webhook(
                settings, sender, watch, delivery, payload
            )
        else:
            outcome, status_code, error = _attempt_email(settings, watch, payload)

        if outcome == "delivered":
            _finalize(delivery, "delivered", status_code, None, now)
            delivery.delivered_at = now
            watch.last_delivered_at = now
            counts["delivered"] += 1
        elif outcome == "retry" and delivery.attempt_count < settings.webhook_max_attempts:
            delivery.status = "retrying"
            delivery.last_status_code = status_code
            delivery.last_error_redacted = error
            delivery.next_attempt_at = now + timedelta(
                seconds=backoff_seconds(delivery.attempt_count, settings.webhook_retry_base_seconds)
            )
            counts["retrying"] += 1
        else:
            _finalize(delivery, "failed", status_code, error, now)
            counts["failed"] += 1
        db.flush()
    db.commit()
    return counts


def _target(db: Session, delivery: NotificationDelivery, now: datetime):
    """(watch, payload, why it cannot be sent) for a filing or a listing delivery."""
    if delivery.listing_watch_id is not None:
        watch = db.get(ListingWatch, delivery.listing_watch_id)
        event = (
            db.get(ListingEvent, delivery.listing_event_id) if delivery.listing_event_id else None
        )
        if watch is None or event is None:
            return None, None, "watch or listing event missing"
        market = db.scalar(select(Market).where(Market.mic == event.mic))
        return watch, build_listing_payload(delivery, event, market, now), None
    watch = db.get(CompanyWatch, delivery.watch_id) if delivery.watch_id else None
    filing = db.get(Filing, delivery.filing_id) if delivery.filing_id else None
    if watch is None or filing is None:
        return None, None, "watch or filing missing"
    return watch, build_event_payload(delivery, filing, now), None


def _finalize(delivery, status, status_code, error, now):
    delivery.status = status
    delivery.last_status_code = status_code
    delivery.last_error_redacted = error
    delivery.next_attempt_at = None


def _attempt_webhook(settings, sender, watch, delivery, payload):
    body = encode_payload(payload)
    secret = derive_watch_secret(settings.webhook_signing_secret, str(watch.id))
    ts = int(time.time())
    headers = {
        "Content-Type": "application/json",
        "X-Event-Id": delivery.event_id,
        "X-Event-Type": payload["event_type"],
        "X-Signature-Timestamp": str(ts),
        "X-Signature": sign_webhook(secret, ts, body),
        "Idempotency-Key": delivery.event_id,
    }
    try:
        resp = sender.send(watch.destination, body, headers)
    except UnsafeDestination as exc:
        return "failed", None, f"destination rejected: {exc}"[:200]
    except httpx.TimeoutException:
        return "retry", None, "timeout"
    except httpx.HTTPError as exc:
        return "retry", None, f"network error: {type(exc).__name__}"
    code = resp.status_code
    if 200 <= code < 300:
        log_event(
            logger, logging.INFO, "webhook delivered", event_id=delivery.event_id, status=code
        )
        return "delivered", code, None
    if code in RETRYABLE_STATUSES:
        return "retry", code, f"destination returned {code}"
    if 300 <= code < 400:
        return "failed", code, "destination redirected; redirects are not followed"
    return "failed", code, f"destination returned {code}"


def _attempt_email(settings, watch, payload):
    if not settings.email_configured:
        return "failed", None, "email delivery is not configured on this deployment"
    try:
        from app.services.email_adapter import send_filing_email, send_listing_email

        send = send_filing_email if payload["event_type"] == EVENT_TYPE else send_listing_email
        send(settings, watch.destination, payload)
        return "delivered", None, None
    except Exception as exc:  # noqa: BLE001 - provider errors are redacted and retried
        return "retry", None, f"email error: {type(exc).__name__}"
