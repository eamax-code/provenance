from __future__ import annotations

from fastapi import APIRouter, Depends, Path, Request, Response
from sqlalchemy.orm import Session

from app.api.dependencies import client_ip, db_session, enforce_ip_limit, settings_dep
from app.core.config import Settings
from app.core.errors import APIError
from app.core.rate_limits import FixedWindowRateLimiter
from app.schemas.common import ErrorEnvelope
from app.schemas.public import PublicCompanyBundle, PublicPlans, ShowcaseList
from app.services import public as public_service
from app.services.sec_client import normalize_cik

router = APIRouter(prefix="/v1/public", tags=["public"])

PUBLIC_RATE_LIMIT_PER_MINUTE = 60
ip_limiter = FixedWindowRateLimiter(window_seconds=60)
_ERRORS = {
    404: {"model": ErrorEnvelope},
    422: {"model": ErrorEnvelope},
    429: {"model": ErrorEnvelope},
}


def _guard(request: Request, response: Response) -> None:
    enforce_ip_limit(
        ip_limiter,
        "public:" + client_ip(request),
        PUBLIC_RATE_LIMIT_PER_MINUTE,
        "Too many requests to the public endpoints from this address.",
    )
    response.headers["Cache-Control"] = f"public, max-age={public_service.CACHE_TTL_SECONDS}"


@router.get(
    "/plans",
    response_model=PublicPlans,
    responses=_ERRORS,
    summary="Plan limits and pilot pricing (public)",
)
def plans(request: Request, response: Response, settings: Settings = Depends(settings_dep)):
    _guard(request, response)
    return public_service.public_plans(settings)


@router.get(
    "/companies",
    response_model=ShowcaseList,
    responses=_ERRORS,
    summary="Showcase companies this deployment has ingested (public)",
)
def companies(
    request: Request,
    response: Response,
    db: Session = Depends(db_session),
    settings: Settings = Depends(settings_dep),
):
    _guard(request, response)
    return public_service.public_companies(db, settings)


@router.get(
    "/companies/{cik}",
    response_model=PublicCompanyBundle,
    responses=_ERRORS,
    summary="Public company page bundle: profile, filings, annual facts, freshness",
    description="Only companies in the showcase are available. Never triggers SEC requests.",
)
def company(
    request: Request,
    response: Response,
    cik: str = Path(max_length=13),
    db: Session = Depends(db_session),
    settings: Settings = Depends(settings_dep),
):
    _guard(request, response)
    try:
        normalize_cik(cik)
    except ValueError as exc:
        raise APIError(422, "invalid_parameter", "cik must be 1-10 digits.") from exc
    bundle = public_service.company_bundle(db, settings, cik)
    if bundle is None:
        raise APIError(404, "company_not_found", "This company is not part of the public showcase.")
    return bundle


@router.get(
    "/listings/events",
    responses=_ERRORS,
    summary="Recent new listings, delistings and suspensions on covered venues (public)",
)
def listing_events(
    request: Request,
    response: Response,
    db: Session = Depends(db_session),
):
    _guard(request, response)
    return public_service.public_listing_events(db)
