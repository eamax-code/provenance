"""Event feed (ADR 0007): new SEC filings and listing events, by polling or Server-Sent Events."""

from __future__ import annotations

import asyncio
import json
import threading
import time
from collections.abc import AsyncIterator
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Header, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from app.api.dependencies import db_session, require_api_key, require_reader, settings_dep
from app.core.config import Settings, plan_limits
from app.core.errors import APIError
from app.db.models import ApiKey, utcnow
from app.db.session import session_factory
from app.schemas.common import ErrorEnvelope
from app.services import events as feed
from app.services.sec_client import normalize_cik

router = APIRouter(prefix="/v1/events", tags=["events"])

_ERRORS = {
    401: {"model": ErrorEnvelope},
    403: {"model": ErrorEnvelope},
    422: {"model": ErrorEnvelope},
    429: {"model": ErrorEnvelope},
}

NOTES = [
    "Events are new SEC filings (type sec.filing.detected) and international listing events "
    "(type listing.<event_type>). Backfill never appears: a company's first ingestion, older "
    "history pages and filings older than the notification age are excluded.",
    "Order is the time the event entered this feed (stream_at), then kind and id. Pass "
    "next_cursor as `after` to continue; the cursor is opaque.",
    "Events appear a few seconds after ingestion commits, so the feed never skips a row that "
    "was still being written.",
]

# Concurrent SSE connections per API key on this process (multi-replica limits: ticket 12).
_open_streams: dict[str, int] = {}
_streams_lock = threading.Lock()


class EventOut(BaseModel):
    id: str = Field(description="Opaque cursor of this event; resume with after=<id>")
    type: str = Field(description="sec.filing.detected | listing.<event_type>")
    kind: str = Field(description="filing | listing")
    stream_at: str = Field(description="When the event entered this feed (UTC)")
    data: dict


class EventPage(BaseModel):
    data: list[EventOut]
    next_cursor: str
    has_more: bool
    notes: list[str]


def _split(value: str | None, max_items: int = 50, upper: bool = False) -> list[str]:
    if not value:
        return []
    items = [v.strip() for v in value.split(",") if v.strip()]
    if len(items) > max_items:
        raise APIError(422, "invalid_parameter", f"At most {max_items} values per filter.")
    return [v.upper() for v in items] if upper else items


def _filters(
    types: str | None,
    cik: str | None,
    form_type: str | None,
    mic: str | None,
    event_type: str | None,
) -> feed.EventFilters:
    kinds = set(_split(types) or feed.KINDS)
    if not kinds <= set(feed.KINDS):
        raise APIError(422, "invalid_parameter", "types must be filing, listing or both.")
    try:
        ciks = [normalize_cik(c) for c in _split(cik)]
    except ValueError as exc:
        raise APIError(422, "invalid_parameter", "cik must be numeric CIKs.") from exc
    forms = _split(form_type, upper=True)
    mics = _split(mic, upper=True)
    event_types = _split(event_type)
    filing_filters, listing_filters = bool(ciks or forms), bool(mics or event_types)
    if filing_filters and listing_filters:
        raise APIError(
            422,
            "invalid_parameter",
            "Filing filters (cik, form_type) and listing filters (mic, event_type) cannot be "
            "combined; use two requests.",
        )
    if filing_filters:
        kinds &= {"filing"}
    if listing_filters:
        kinds &= {"listing"}
    if not kinds:
        raise APIError(422, "invalid_parameter", "The filters exclude every event type.")
    return feed.EventFilters(
        kinds=tuple(k for k in feed.KINDS if k in kinds),
        ciks=ciks,
        form_types=forms,
        mics=mics,
        event_types=event_types,
    )


def _start(after: str | None, since: datetime | None, settings: Settings, default: datetime):
    if after:
        try:
            return feed.Cursor.decode(after)
        except ValueError as exc:
            raise APIError(422, "invalid_cursor", "The cursor is not valid.") from exc
    if since is None:
        return feed.Cursor.start(default)
    if since.tzinfo is None:
        raise APIError(422, "invalid_parameter", "since must include a timezone, e.g. Z.")
    oldest = utcnow() - timedelta(days=settings.events_max_since_days)
    if since < oldest:
        raise APIError(
            422,
            "invalid_parameter",
            f"since may be at most {settings.events_max_since_days} days ago.",
        )
    return feed.Cursor.start(since)


_FILTER_DOCS = {
    "types": "filing, listing or both (comma-separated)",
    "cik": "Filings for these CIKs only (comma-separated, at most 50)",
    "form_type": "Filings of these form types only, e.g. 8-K,10-Q",
    "mic": "Listing events on these venues only, e.g. XLON,XETA",
    "event_type": "Listing event types, e.g. new_listing,delisting",
}


@router.get("", response_model=EventPage, responses=_ERRORS, summary="Poll the event feed")
def list_events(
    after: str | None = Query(None, max_length=200, description="next_cursor from a prior page"),
    since: datetime | None = Query(
        None, description="Start time when no cursor is given (default: 24 hours ago)"
    ),
    types: str | None = Query(None, max_length=40, description=_FILTER_DOCS["types"]),
    cik: str | None = Query(None, max_length=700, description=_FILTER_DOCS["cik"]),
    form_type: str | None = Query(None, max_length=300, description=_FILTER_DOCS["form_type"]),
    mic: str | None = Query(None, max_length=300, description=_FILTER_DOCS["mic"]),
    event_type: str | None = Query(None, max_length=300, description=_FILTER_DOCS["event_type"]),
    limit: int = Query(50, ge=1, le=100),
    db=Depends(db_session),
    settings: Settings = Depends(settings_dep),
    _key=Depends(require_reader),
):
    filters = _filters(types, cik, form_type, mic, event_type)
    start = _start(after, since, settings, default=utcnow() - timedelta(hours=24))
    until = feed.settled_until(settings.events_settle_seconds)
    page = feed.fetch_page(db, start, until, filters, limit)
    return EventPage(
        data=page.events,
        next_cursor=page.cursor.encode(),
        has_more=page.has_more,
        notes=NOTES,
    )


def _sse(event: dict) -> str:
    body = json.dumps(event, separators=(",", ":"), sort_keys=True)
    return f"id: {event['id']}\nevent: {event['type']}\ndata: {body}\n\n"


@router.get(
    "/stream",
    responses={
        200: {"content": {"text/event-stream": {}}, "description": "Server-Sent Events"},
        **_ERRORS,
    },
    summary="Follow the event feed live (Server-Sent Events)",
)
async def stream_events(
    request: Request,
    after: str | None = Query(None, max_length=200, description="Cursor to resume after"),
    since: datetime | None = Query(
        None, description="Start time when no cursor is given (default: now, new events only)"
    ),
    types: str | None = Query(None, max_length=40, description=_FILTER_DOCS["types"]),
    cik: str | None = Query(None, max_length=700, description=_FILTER_DOCS["cik"]),
    form_type: str | None = Query(None, max_length=300, description=_FILTER_DOCS["form_type"]),
    mic: str | None = Query(None, max_length=300, description=_FILTER_DOCS["mic"]),
    event_type: str | None = Query(None, max_length=300, description=_FILTER_DOCS["event_type"]),
    last_event_id: str | None = Header(None, alias="Last-Event-ID", max_length=200),
    settings: Settings = Depends(settings_dep),
    key: ApiKey = Depends(require_api_key),
):
    """Each event carries `id:` set to its cursor, so a reconnecting client that sends
    `Last-Event-ID` resumes exactly after the last event it received. Idle connections receive
    heartbeat comments and an updated `id:`; connections close after a maximum duration and the
    client reconnects. Browsers' EventSource cannot send X-API-Key, so use a fetch-based client
    or the Python client."""
    filters = _filters(types, cik, form_type, mic, event_type)
    start = _start(last_event_id or after, since, settings, default=utcnow())
    limit = plan_limits(key.plan, settings)["max_event_streams"]
    key_id = str(key.id)
    with _streams_lock:
        if _open_streams.get(key_id, 0) >= limit:
            raise APIError(
                429,
                "stream_limit",
                f"At most {limit} concurrent event streams for this plan.",
                headers={"Retry-After": "30"},
            )
        _open_streams[key_id] = _open_streams.get(key_id, 0) + 1

    async def body() -> AsyncIterator[str]:
        cursor = start
        sent_cursor: feed.Cursor | None = None
        started = last_beat = time.monotonic()
        try:
            retry_ms = int(settings.events_stream_poll_seconds * 1000) + 1000
            yield f"retry: {retry_ms}\n: connected\n\n"
            while True:
                page = await run_in_threadpool(_poll, cursor, filters)
                for event in page.events:
                    yield _sse(event)
                cursor = page.cursor
                if page.events:
                    sent_cursor, last_beat = cursor, time.monotonic()
                if page.has_more:
                    continue
                now = time.monotonic()
                if now - started >= settings.events_stream_max_seconds:
                    if cursor != sent_cursor:
                        yield f"id: {cursor.encode()}\n\n"
                    return
                if now - last_beat >= settings.events_stream_heartbeat_seconds:
                    # An id-only block moves Last-Event-ID forward without firing an event.
                    yield f": heartbeat\nid: {cursor.encode()}\n\n"
                    sent_cursor, last_beat = cursor, now
                if await request.is_disconnected():
                    return
                await asyncio.sleep(settings.events_stream_poll_seconds)
        finally:
            with _streams_lock:
                remaining = _open_streams.get(key_id, 1) - 1
                if remaining > 0:
                    _open_streams[key_id] = remaining
                else:
                    _open_streams.pop(key_id, None)

    def _poll(cursor: feed.Cursor, flt: feed.EventFilters) -> feed.Page:
        db = session_factory()()
        try:
            until = feed.settled_until(settings.events_settle_seconds)
            return feed.fetch_page(db, cursor, until, flt, 100)
        finally:
            db.close()

    return StreamingResponse(
        body(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
