from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.orm import Session

from app.api.dependencies import db_session, settings_dep
from app.core.config import Settings
from app.core.errors import APIError
from app.core.rate_limits import FixedWindowRateLimiter
from app.schemas.common import ErrorEnvelope
from app.services.stats import CACHE_TTL_SECONDS, cached_stats

router = APIRouter(prefix="/v1", tags=["operations"])

STATS_RATE_LIMIT_PER_MINUTE = 30
ip_limiter = FixedWindowRateLimiter(window_seconds=60)


def client_ip(request: Request) -> str:
    # Trust only the direct peer; a reverse proxy should set X-Forwarded-For and the operator
    # can enable trusting it later. Falls back to a shared bucket when unknown.
    return request.client.host if request.client else "unknown"


@router.get(
    "/stats",
    responses={429: {"model": ErrorEnvelope}},
    summary="Public service statistics (no API key)",
    description="Coverage and health counts for this deployment, cached for a short interval. "
    "No customer data, no secrets. Rate limited per client address.",
)
def stats(
    request: Request,
    response: Response,
    db: Session = Depends(db_session),
    settings: Settings = Depends(settings_dep),
):
    decision = ip_limiter.check("ip:" + client_ip(request), STATS_RATE_LIMIT_PER_MINUTE)
    if not decision.allowed:
        raise APIError(
            429,
            "rate_limited",
            "Too many requests to /v1/stats from this address.",
            headers={"Retry-After": str(decision.retry_after_seconds)},
        )
    response.headers["Cache-Control"] = f"public, max-age={CACHE_TTL_SECONDS}"
    return cached_stats(db, settings)
