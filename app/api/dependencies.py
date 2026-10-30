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


def client_ip(request: Request) -> str:
    """Peer address as seen by the server.

    Behind a reverse proxy run uvicorn with --proxy-headers and --forwarded-allow-ips so the
    peer address is the real client, otherwise every visitor shares one rate-limit bucket.
    """
    return request.client.host if request.client else "unknown"


def enforce_ip_limit(limiter: FixedWindowRateLimiter, key: str, limit: int, message: str) -> None:
    decision = limiter.check(key, limit)
    if not decision.allowed:
        raise APIError(
            429,
            "rate_limited",
            message,
            headers={"Retry-After": str(decision.retry_after_seconds)},
        )


# ---- public demo key ---------------------------------------------------------------------

DEMO_KEY = "demo"
demo_minute_limiter = FixedWindowRateLimiter(window_seconds=60)
demo_day_limiter = FixedWindowRateLimiter(window_seconds=86400)
DEMO_UPGRADE = "Request a free key at /#contact for full access."


class DemoPrincipal:
    """Stand-in for an ApiKey on read-only endpoints when the public demo key is used."""

    id = None
    plan = "demo"
    key_prefix = "demo"


def require_reader(
    request: Request,
    raw_key: str | None = Depends(api_key_header),
    db: Session = Depends(db_session),
    settings: Settings = Depends(settings_dep),
):
    """Read-only endpoints: a real key, or the public demo key with tight limits.

    The demo key may be passed as ?api_key=demo so example URLs work in a browser; real keys are
    never accepted from the query string.
    """
    is_demo = raw_key == DEMO_KEY or (
        not raw_key and request.query_params.get("api_key") == DEMO_KEY
    )
    if not is_demo:
        return require_api_key(request, raw_key, db, settings)
    if not settings.demo_key_enabled:
        raise APIError(401, "invalid_api_key", "The demo key is disabled on this deployment.")
    ip = client_ip(request)
    enforce_ip_limit(
        demo_minute_limiter,
        "demo-min:" + ip,
        settings.demo_rate_limit_per_minute,
        f"Demo key rate limit reached ({settings.demo_rate_limit_per_minute}/minute). "
        f"Request a free key for 60/minute: {DEMO_UPGRADE}",
    )
    enforce_ip_limit(
        demo_day_limiter,
        "demo-day:" + ip,
        settings.demo_requests_per_day,
        f"Demo key daily limit reached. Request a free key for full access: {DEMO_UPGRADE}",
    )
    raw_limit = request.query_params.get("limit")
    if raw_limit and raw_limit.isdigit() and int(raw_limit) > settings.demo_max_limit:
        raise APIError(
            403,
            "demo_limit",
            f"The demo key returns at most limit={settings.demo_max_limit} rows. {DEMO_UPGRADE}",
        )
    cik = request.path_params.get("cik")
    if cik is not None:
        from app.services.public import showcase_ciks
        from app.services.sec_client import normalize_cik

        try:
            wanted = normalize_cik(cik)
        except ValueError:
            wanted = None
        allowed, _ = showcase_ciks(db, settings)
        if wanted not in allowed:
            raise APIError(
                403,
                "demo_scope",
                "The demo key covers the public showcase companies only"
                + (
                    f" ({', '.join(allowed[:5])}{'…' if len(allowed) > 5 else ''})"
                    if allowed
                    else ""
                )
                + f". {DEMO_UPGRADE}",
            )
    request.state.demo = True
    return DemoPrincipal()
