from __future__ import annotations

import re
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.dependencies import db_session, require_api_key, settings_dep
from app.core.config import Settings, plan_limits
from app.core.errors import APIError
from app.core.security import derive_watch_secret, hash_secret
from app.core.ssrf import UnsafeDestination, validate_webhook_url
from app.db.models import ApiKey, AuditEvent, Company, CompanyWatch, NotificationDelivery, utcnow
from app.schemas.common import ErrorEnvelope, PageMeta
from app.schemas.watches import (
    DeliveryList,
    DeliveryOut,
    WatchCreate,
    WatchCreated,
    WatchList,
    WatchOut,
)
from app.services.sec_client import normalize_cik
from app.services.usage import watched_companies_used

router = APIRouter(prefix="/v1", tags=["watches"])

_ERRORS = {
    401: {"model": ErrorEnvelope},
    404: {"model": ErrorEnvelope},
    422: {"model": ErrorEnvelope},
}
_EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,255}\.[A-Za-z]{2,}$")


@router.post("/watches", response_model=WatchCreated, status_code=201, responses=_ERRORS)
def create_watch(
    body: WatchCreate,
    request: Request,
    db: Session = Depends(db_session),
    settings: Settings = Depends(settings_dep),
    key: ApiKey = Depends(require_api_key),
):
    try:
        cik = normalize_cik(body.cik)
    except ValueError as exc:
        raise APIError(422, "invalid_parameter", "cik must be 1-10 digits.") from exc
    company = db.scalar(select(Company).where(Company.cik == cik))
    if company is None:
        raise APIError(
            404,
            "company_not_found",
            "Company must be known before it can be watched. "
            "Request GET /v1/companies/{cik} first.",
        )
    destination = body.destination.strip()
    if body.destination_type == "webhook":
        try:
            destination = validate_webhook_url(
                destination, allow_private=settings.webhook_allow_private_destinations
            )
        except UnsafeDestination as exc:
            raise APIError(422, "invalid_destination", str(exc)) from exc
    else:
        if not settings.email_configured:
            raise APIError(
                422,
                "email_delivery_not_configured",
                "Email notifications are not configured on this deployment; use a webhook.",
            )
        if not _EMAIL_RE.match(destination) or len(destination) > 254:
            raise APIError(422, "invalid_destination", "destination must be a valid email address.")

    limits = plan_limits(key.plan, settings)
    already_watched = db.scalar(
        select(CompanyWatch.id).where(
            CompanyWatch.api_key_id == key.id,
            CompanyWatch.cik == cik,
            CompanyWatch.is_active.is_(True),
        )
    )
    if already_watched is None and watched_companies_used(db, key.id) >= limits["max_watches"]:
        raise APIError(
            422,
            "watch_limit_reached",
            f"Your plan allows watching {limits['max_watches']} companies. "
            "Deactivate a watch or upgrade.",
        )

    now = utcnow()
    watch = CompanyWatch(
        api_key_id=key.id,
        cik=cik,
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
            action="watch.created",
            subject_type="watch",
            subject_id=str(watch.id),
            occurred_at=now,
        )
    )
    db.commit()
    out = WatchCreated.model_validate(watch)
    out.webhook_secret = secret
    return out


@router.get("/watches", response_model=WatchList, responses=_ERRORS)
def list_watches(
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    include_inactive: bool = Query(False),
    db: Session = Depends(db_session),
    key: ApiKey = Depends(require_api_key),
):
    stmt = select(CompanyWatch).where(CompanyWatch.api_key_id == key.id)
    if not include_inactive:
        stmt = stmt.where(CompanyWatch.is_active.is_(True))
    rows = db.scalars(
        stmt.order_by(CompanyWatch.created_at.desc()).offset(offset).limit(limit + 1)
    ).all()
    has_more = len(rows) > limit
    return WatchList(
        data=[WatchOut.model_validate(w) for w in rows[:limit]],
        meta=PageMeta(
            limit=limit,
            offset=offset,
            has_more=has_more,
            next_offset=offset + limit if has_more else None,
        ),
    )


@router.delete("/watches/{watch_id}", response_model=WatchOut, responses=_ERRORS)
def deactivate_watch(
    watch_id: UUID,
    db: Session = Depends(db_session),
    key: ApiKey = Depends(require_api_key),
):
    watch = db.scalar(
        select(CompanyWatch).where(CompanyWatch.id == watch_id, CompanyWatch.api_key_id == key.id)
    )
    if watch is None:
        raise APIError(404, "watch_not_found", "No watch with this id belongs to your API key.")
    if watch.is_active:
        now = utcnow()
        watch.is_active = False
        watch.deactivated_at = now
        db.add(
            AuditEvent(
                actor=f"api_key:{key.key_prefix}",
                action="watch.deactivated",
                subject_type="watch",
                subject_id=str(watch.id),
                occurred_at=now,
            )
        )
        db.commit()
    return WatchOut.model_validate(watch)


@router.get("/watches/{watch_id}/deliveries", response_model=DeliveryList, responses=_ERRORS)
def list_deliveries(
    watch_id: UUID,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(db_session),
    key: ApiKey = Depends(require_api_key),
):
    watch = db.scalar(
        select(CompanyWatch).where(CompanyWatch.id == watch_id, CompanyWatch.api_key_id == key.id)
    )
    if watch is None:
        raise APIError(404, "watch_not_found", "No watch with this id belongs to your API key.")
    rows = db.scalars(
        select(NotificationDelivery)
        .where(NotificationDelivery.watch_id == watch.id)
        .order_by(NotificationDelivery.created_at.desc())
        .offset(offset)
        .limit(limit + 1)
    ).all()
    has_more = len(rows) > limit
    return DeliveryList(
        data=[DeliveryOut.model_validate(d) for d in rows[:limit]],
        meta=PageMeta(
            limit=limit,
            offset=offset,
            has_more=has_more,
            next_offset=offset + limit if has_more else None,
        ),
    )
