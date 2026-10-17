from __future__ import annotations

import logging
from collections.abc import Generator
from datetime import UTC, datetime, timedelta

from fastapi import Depends, Request
from fastapi.security import APIKeyHeader
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings, plan_limits
from app.core.errors import APIError
from app.core.rate_limits import FixedWindowRateLimiter
from app.core.security import constant_time_equals, hash_api_key
from app.db.models import ApiKey
from app.db.session import get_db
from app.services.usage import requests_this_month

logger = logging.getLogger("app.auth")

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False, scheme_name="ApiKeyAuth")
admin_token_header = APIKeyHeader(name="X-Admin-Token", auto_error=False, scheme_name="AdminToken")

rate_limiter = FixedWindowRateLimiter(window_seconds=60)


def db_session() -> Generator[Session, None, None]:
    yield from get_db()


def settings_dep(request: Request) -> Settings:
    return getattr(request.app.state, "settings", None) or get_settings()


def require_api_key(
    request: Request,
    raw_key: str | None = Depends(api_key_header),
    db: Session = Depends(db_session),
    settings: Settings = Depends(settings_dep),
) -> ApiKey:
    if not raw_key:
        raise APIError(401, "missing_api_key", "Provide your API key in the X-API-Key header.")
    if len(raw_key) > 200:
        raise APIError(401, "invalid_api_key", "The API key is invalid.")
    key_hash = hash_api_key(raw_key, settings.api_key_pepper)
    key = db.scalar(select(ApiKey).where(ApiKey.key_hash == key_hash))
    if key is None or not key.is_active or key.revoked_at is not None:
        raise APIError(401, "invalid_api_key", "The API key is invalid or has been revoked.")

    limits = plan_limits(key.plan, settings)
    decision = rate_limiter.check(str(key.id), limits["rate_limit_per_minute"])
    request.state.api_key_id = key.id
    request.state.rate_limit = decision
    if not decision.allowed:
        raise APIError(
            429,
            "rate_limited",
            "Per-minute rate limit exceeded for this API key.",
            headers={
                "Retry-After": str(decision.retry_after_seconds),
                "X-RateLimit-Limit": str(decision.limit),
                "X-RateLimit-Remaining": "0",
            },
        )
    used = requests_this_month(db, key.id)
    if used >= limits["monthly_request_quota"]:
        now = datetime.now(UTC)
        next_month = (now.replace(day=28) + timedelta(days=4)).replace(
            day=1, hour=0, minute=0, second=0, microsecond=0
        )
        raise APIError(
            429,
            "quota_exceeded",
            "Monthly request quota exceeded for this plan.",
            headers={"Retry-After": str(int((next_month - now).total_seconds()))},
        )
    key.last_used_at = datetime.now(UTC)
    db.commit()
    return key


def require_admin(
    token: str | None = Depends(admin_token_header),
    settings: Settings = Depends(settings_dep),
) -> str:
    if not settings.admin_token:
        raise APIError(
            503,
            "admin_endpoint_disabled",
            "Admin operations are disabled: ADMIN_TOKEN is not configured. "
            "Use scripts/create_api_key.py instead.",
        )
    if not token or not constant_time_equals(token, settings.admin_token):
        raise APIError(403, "forbidden", "A valid X-Admin-Token header is required.")
    return "admin"
