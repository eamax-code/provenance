from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.dependencies import db_session, require_admin, require_api_key, settings_dep
from app.core.config import Settings, plan_limits
from app.core.errors import APIError
from app.core.security import generate_api_key
from app.db.models import ApiKey, AuditEvent, utcnow
from app.schemas.common import ErrorEnvelope
from app.schemas.developer import (
    ApiKeyCreate,
    ApiKeyCreated,
    ApiKeyList,
    ApiKeyOut,
    PlanInfo,
    UsageOut,
)
from app.services.usage import requests_this_month, usage_summary, watched_companies_used

router = APIRouter(prefix="/v1/developer", tags=["developer"])
_ERRORS = {
    401: {"model": ErrorEnvelope},
    403: {"model": ErrorEnvelope},
    404: {"model": ErrorEnvelope},
    503: {"model": ErrorEnvelope},
}


def create_key_record(
    db: Session, settings: Settings, owner_email: str, plan: str, label: str | None, actor: str
):
    env = "test" if settings.app_env in ("development", "test") else "live"
    generated = generate_api_key(settings.api_key_pepper, env=env)
    now = utcnow()
    key = ApiKey(
        owner_email=owner_email.lower(),
        key_prefix=generated.key_prefix,
        key_hash=generated.key_hash,
        plan=plan,
        label=label,
        is_active=True,
        created_at=now,
    )
    db.add(key)
    db.flush()
    db.add(
        AuditEvent(
            actor=actor,
            action="api_key.created",
            subject_type="api_key",
            subject_id=str(key.id),
            occurred_at=now,
        )
    )
    db.commit()
    return key, generated.raw_key


@router.post(
    "/api-keys",
    response_model=ApiKeyCreated,
    status_code=201,
    responses=_ERRORS,
    summary="Create an API key (admin token required)",
    description="Protected by X-Admin-Token. Public self-serve signup is not part of the MVP; "
    "see README for the onboarding flow. The raw key is returned exactly once.",
)
def create_api_key(
    body: ApiKeyCreate,
    db: Session = Depends(db_session),
    settings: Settings = Depends(settings_dep),
    _admin: str = Depends(require_admin),
):
    key, raw = create_key_record(
        db, settings, body.owner_email, body.plan, body.label, actor="admin"
    )
    return ApiKeyCreated(**ApiKeyOut.model_validate(key).model_dump(), api_key=raw)


@router.get(
    "/api-keys",
    response_model=ApiKeyList,
    responses=_ERRORS,
    summary="List keys owned by the caller's email",
)
def list_api_keys(db: Session = Depends(db_session), key: ApiKey = Depends(require_api_key)):
    rows = db.scalars(
        select(ApiKey).where(ApiKey.owner_email == key.owner_email).order_by(ApiKey.created_at)
    ).all()
    return ApiKeyList(data=[ApiKeyOut.model_validate(k) for k in rows])


@router.delete(
    "/api-keys/{key_id}",
    response_model=ApiKeyOut,
    responses=_ERRORS,
    summary="Revoke a key you own",
)
def revoke_api_key(
    key_id: UUID, db: Session = Depends(db_session), key: ApiKey = Depends(require_api_key)
):
    target = db.scalar(
        select(ApiKey).where(ApiKey.id == key_id, ApiKey.owner_email == key.owner_email)
    )
    if target is None:
        raise APIError(404, "api_key_not_found", "No API key with this id belongs to you.")
    if target.is_active:
        now = utcnow()
        target.is_active = False
        target.revoked_at = now
        db.add(
            AuditEvent(
                actor=f"api_key:{key.key_prefix}",
                action="api_key.revoked",
                subject_type="api_key",
                subject_id=str(target.id),
                occurred_at=now,
            )
        )
        db.commit()
    return ApiKeyOut.model_validate(target)


@router.get("/usage", response_model=UsageOut, response_model_by_alias=True, responses=_ERRORS)
def usage(
    from_: datetime | None = Query(None, alias="from"),
    to: datetime | None = Query(None),
    db: Session = Depends(db_session),
    settings: Settings = Depends(settings_dep),
    key: ApiKey = Depends(require_api_key),
):
    now = datetime.now(UTC)
    end = (
        (to or now).astimezone(UTC)
        if (to and to.tzinfo)
        else (to.replace(tzinfo=UTC) if to else now)
    )
    start = (
        from_.astimezone(UTC)
        if (from_ and from_.tzinfo)
        else (from_.replace(tzinfo=UTC) if from_ else end - timedelta(days=30))
    )
    if start >= end:
        raise APIError(422, "invalid_parameter", "'from' must be earlier than 'to'.")
    summary = usage_summary(db, key.id, start, end)
    limits = plan_limits(key.plan, settings)
    return UsageOut(
        **{"from": start},
        to=end,
        **summary,
        plan=PlanInfo(
            plan=key.plan,
            rate_limit_per_minute=limits["rate_limit_per_minute"],
            monthly_request_quota=limits["monthly_request_quota"],
            monthly_requests_used=requests_this_month(db, key.id, now),
            max_export_rows=limits["max_export_rows"],
            max_watches=limits["max_watches"],
            watched_companies_used=watched_companies_used(db, key.id),
        ),
    )
