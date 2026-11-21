"""Type watches (launch plan T-01): "tell me about any restatement", across every company or a
universe (SIC prefix, exchange, filer category or up to 500 CIKs), as signed webhooks.

Rare types (restatement, auditor change, bankruptcy, change in control, late filing,
deregistration, delisting, tender offer, merger proxy, acquisition completed) are delivered one
filing at a time. High-volume types (results, material agreements, shareholder votes) need a
universe to be delivered one at a time; without one they arrive as one batch an hour. Same
signing as filing watches (ADR 0001); backfill never notifies (ADR 0004). Builder plan and up.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.dependencies import db_session, require_api_key, settings_dep
from app.api.routes_notifications import validated_destination
from app.core.config import Settings, plan_limits
from app.core.errors import APIError
from app.core.plans import PLANS
from app.core.security import derive_watch_secret, hash_secret
from app.db.models import ApiKey, AuditEvent, TypeWatch, utcnow
from app.schemas.common import ErrorEnvelope, PageMeta
from app.schemas.watches import TypeWatchCreate, TypeWatchCreated, TypeWatchList, TypeWatchOut
from app.services import filing_events, insider_activity
from app.services.sec_client import normalize_cik
from app.services.usage import active_watches_used, watched_companies_used

router = APIRouter(prefix="/v1/type-watches", tags=["watches"])
_ERRORS = {
    401: {"model": ErrorEnvelope},
    403: {"model": ErrorEnvelope},
    404: {"model": ErrorEnvelope},
    422: {"model": ErrorEnvelope},
}


def _audit(db: Session, key: ApiKey, action: str, watch: TypeWatch, now) -> None:
    db.add(
        AuditEvent(
            actor=f"api_key:{key.key_prefix}", action=action, subject_type="type_watch",
            subject_id=str(watch.id), occurred_at=now,
        )
    )  # fmt: skip


@router.post(
    "",
    response_model=TypeWatchCreated,
    status_code=201,
    responses=_ERRORS,
    summary="Watch filing event types across companies (Builder plan and up)",
)
def create_type_watch(
    body: TypeWatchCreate,
    db: Session = Depends(db_session),
    settings: Settings = Depends(settings_dep),
    key: ApiKey = Depends(require_api_key),
):
    plan = PLANS.get(key.plan)
    if plan is None or not plan.type_watches:
        raise APIError(
            403,
            "plan_upgrade_required",
            "Watches on event types across companies are on the Builder plan and up; "
            "company watches (POST /v1/watches) work on every plan.",
        )
    types = sorted(set(body.event_types))
    accepted = list(filing_events.FILING_EVENT_TYPES) + list(insider_activity.TYPES)
    unknown = [t for t in types if t not in accepted]
    if unknown:
        raise APIError(
            422,
            "invalid_parameter",
            f"Unknown event type: {', '.join(unknown)}. Accepted: {', '.join(accepted)}.",
        )
    try:
        ciks = sorted({normalize_cik(c) for c in body.ciks or []})
    except ValueError as exc:
        raise APIError(422, "invalid_parameter", "ciks must be 1-10 digits each.") from exc
    destination = validated_destination("webhook", body.destination, settings)
    limits = plan_limits(key.plan, settings)
    if watched_companies_used(db, key.id) >= limits["max_watches"]:
        raise APIError(
            422,
            "watch_limit_reached",
            f"Your plan allows {limits['max_watches']} watches; a type watch counts as one.",
        )
    if active_watches_used(db, key.id) >= limits["max_active_watches"]:
        raise APIError(
            422,
            "watch_limit_reached",
            f"Your plan allows {limits['max_active_watches']} active watches in total.",
        )
    universe = bool(body.sic_prefix or body.exchange or body.filer_category or ciks)
    busy = bool(set(types) & filing_events.HIGH_VOLUME)
    now = utcnow()
    watch = TypeWatch(
        api_key_id=key.id,
        event_types=",".join(types),
        sic_prefix=body.sic_prefix,
        exchange=body.exchange,
        filer_category=body.filer_category,
        ciks=",".join(ciks) or None,
        delivery_mode="hourly" if busy and not universe else "immediate",
        destination_type="webhook",
        destination=destination,
        is_active=True,
        created_at=now,
    )
    db.add(watch)
    db.flush()
    secret = derive_watch_secret(settings.webhook_signing_secret, str(watch.id))
    watch.secret_hash = hash_secret(secret)
    _audit(db, key, "type_watch.created", watch, now)
    db.commit()
    return TypeWatchCreated(
        **TypeWatchOut.model_validate(watch).model_dump(), webhook_secret=secret
    )


def _own(db: Session, watch_id: UUID, key: ApiKey) -> TypeWatch:
    watch = db.scalar(
        select(TypeWatch).where(TypeWatch.id == watch_id, TypeWatch.api_key_id == key.id)
    )
    if watch is None:
        raise APIError(404, "watch_not_found", "No type watch with this id belongs to your key.")
    return watch


@router.get("", response_model=TypeWatchList, responses=_ERRORS, summary="Your type watches")
def list_type_watches(
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    include_inactive: bool = Query(False),
    db: Session = Depends(db_session),
    key: ApiKey = Depends(require_api_key),
):
    stmt = select(TypeWatch).where(TypeWatch.api_key_id == key.id)
    if not include_inactive:
        stmt = stmt.where(TypeWatch.is_active.is_(True))
    rows = db.scalars(
        stmt.order_by(TypeWatch.created_at.desc()).offset(offset).limit(limit + 1)
    ).all()
    has_more = len(rows) > limit
    return TypeWatchList(
        data=[TypeWatchOut.model_validate(w) for w in rows[:limit]],
        meta=PageMeta(
            limit=limit, offset=offset, has_more=has_more,
            next_offset=offset + limit if has_more else None,
        ),
    )  # fmt: skip


@router.delete(
    "/{watch_id}", response_model=TypeWatchOut, responses=_ERRORS, summary="Stop a type watch"
)
def deactivate_type_watch(
    watch_id: UUID, db: Session = Depends(db_session), key: ApiKey = Depends(require_api_key)
):
    watch = _own(db, watch_id, key)
    if watch.is_active:
        now = utcnow()
        watch.is_active = False
        watch.deactivated_at = now
        _audit(db, key, "type_watch.deactivated", watch, now)
        db.commit()
    return TypeWatchOut.model_validate(watch)
