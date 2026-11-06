"""Watches on listing events: new listings, delistings, suspensions on a venue, a country or a
region, delivered as signed webhooks or emails (ticket 09). Same delivery and signing design as
filing watches (docs/adr/0004)."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.dependencies import db_session, require_api_key, settings_dep
from app.api.routes_notifications import validated_destination
from app.core.config import Settings, plan_limits
from app.core.errors import APIError
from app.core.security import derive_watch_secret, hash_secret
from app.db.models import ApiKey, AuditEvent, ListingWatch, Market, NotificationDelivery, utcnow
from app.schemas.common import ErrorEnvelope, PageMeta
from app.schemas.watches import (
    ListingDeliveryList,
    ListingDeliveryOut,
    ListingWatchCreate,
    ListingWatchCreated,
    ListingWatchList,
    ListingWatchOut,
)
from app.services.markets.records import EVENT_TYPES
from app.services.usage import active_watches_used

router = APIRouter(prefix="/v1/listing-watches", tags=["watches"])
_ERRORS = {
    401: {"model": ErrorEnvelope},
    404: {"model": ErrorEnvelope},
    422: {"model": ErrorEnvelope},
}
REGIONS = ("canada", "europe", "uk")


def _scope(db: Session, scope_type: str, value: str) -> str:
    value = value.strip()
    if scope_type == "region":
        if value.lower() not in REGIONS:
            raise APIError(
                422, "invalid_parameter", f"region must be one of: {', '.join(REGIONS)}."
            )
        return value.lower()
    value = value.upper()
    column = Market.mic if scope_type == "mic" else Market.country
    if db.scalar(select(Market.mic).where(column == value).limit(1)) is None:
        what = "venue (MIC)" if scope_type == "mic" else "country"
        raise APIError(
            422, "invalid_parameter", f"No covered {what} {value}; see GET /v1/markets/."
        )
    return value


@router.post("", response_model=ListingWatchCreated, status_code=201, responses=_ERRORS)
def create_listing_watch(
    body: ListingWatchCreate,
    db: Session = Depends(db_session),
    settings: Settings = Depends(settings_dep),
    key: ApiKey = Depends(require_api_key),
):
    unknown = [t for t in body.event_types if t not in EVENT_TYPES]
    if unknown or not body.event_types:
        raise APIError(
            422, "invalid_parameter", f"event_types must be among: {', '.join(EVENT_TYPES)}."
        )
    scope_value = _scope(db, body.scope_type, body.scope_value)
    destination = validated_destination(body.destination_type, body.destination, settings)
    limits = plan_limits(key.plan, settings)
    if active_watches_used(db, key.id) >= limits["max_active_watches"]:
        raise APIError(
            422,
            "watch_limit_reached",
            f"Your plan allows {limits['max_active_watches']} active watches in total. "
            "Deactivate a watch or upgrade.",
        )
    now = utcnow()
    watch = ListingWatch(
        api_key_id=key.id,
        scope_type=body.scope_type,
        scope_value=scope_value,
        event_types=",".join(dict.fromkeys(body.event_types)),
        destination_type=body.destination_type,
        destination=destination,
        is_active=True,
        created_at=now,
    )
    db.add(watch)
    db.flush()
    secret = None
    if body.destination_type == "webhook":
        secret = derive_watch_secret(settings.webhook_signing_secret, str(watch.id))
        watch.secret_hash = hash_secret(secret)
    db.add(
        AuditEvent(
            actor=f"api_key:{key.key_prefix}",
            action="listing_watch.created",
            subject_type="listing_watch",
            subject_id=str(watch.id),
            occurred_at=now,
        )
    )
    db.commit()
    out = ListingWatchCreated.model_validate(watch)
    out.webhook_secret = secret
    return out


def _own(db: Session, watch_id: UUID, key: ApiKey) -> ListingWatch:
    watch = db.scalar(
        select(ListingWatch).where(ListingWatch.id == watch_id, ListingWatch.api_key_id == key.id)
    )
    if watch is None:
        raise APIError(404, "watch_not_found", "No listing watch with this id belongs to your key.")
    return watch


@router.get("", response_model=ListingWatchList, responses=_ERRORS)
def list_listing_watches(
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    include_inactive: bool = Query(False),
    db: Session = Depends(db_session),
    key: ApiKey = Depends(require_api_key),
):
    stmt = select(ListingWatch).where(ListingWatch.api_key_id == key.id)
    if not include_inactive:
        stmt = stmt.where(ListingWatch.is_active.is_(True))
    rows = db.scalars(
        stmt.order_by(ListingWatch.created_at.desc()).offset(offset).limit(limit + 1)
    ).all()
    has_more = len(rows) > limit
    return ListingWatchList(
        data=[ListingWatchOut.model_validate(w) for w in rows[:limit]],
        meta=PageMeta(
            limit=limit,
            offset=offset,
            has_more=has_more,
            next_offset=offset + limit if has_more else None,
        ),
    )


@router.delete("/{watch_id}", response_model=ListingWatchOut, responses=_ERRORS)
def deactivate_listing_watch(
    watch_id: UUID, db: Session = Depends(db_session), key: ApiKey = Depends(require_api_key)
):
    watch = _own(db, watch_id, key)
    if watch.is_active:
        now = utcnow()
        watch.is_active = False
        watch.deactivated_at = now
        db.add(
            AuditEvent(
                actor=f"api_key:{key.key_prefix}",
                action="listing_watch.deactivated",
                subject_type="listing_watch",
                subject_id=str(watch.id),
                occurred_at=now,
            )
        )
        db.commit()
    return ListingWatchOut.model_validate(watch)


@router.get("/{watch_id}/deliveries", response_model=ListingDeliveryList, responses=_ERRORS)
def list_listing_deliveries(
    watch_id: UUID,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(db_session),
    key: ApiKey = Depends(require_api_key),
):
    watch = _own(db, watch_id, key)
    rows = db.scalars(
        select(NotificationDelivery)
        .where(NotificationDelivery.listing_watch_id == watch.id)
        .order_by(NotificationDelivery.created_at.desc())
        .offset(offset)
        .limit(limit + 1)
    ).all()
    has_more = len(rows) > limit
    return ListingDeliveryList(
        data=[ListingDeliveryOut.model_validate(d) for d in rows[:limit]],
        meta=PageMeta(
            limit=limit,
            offset=offset,
            has_more=has_more,
            next_offset=offset + limit if has_more else None,
        ),
    )
