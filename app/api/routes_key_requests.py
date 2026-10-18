from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.orm import Session

from app.api.dependencies import client_ip, db_session, enforce_ip_limit, settings_dep
from app.core.config import SELF_SERVE_PLANS, Settings
from app.core.rate_limits import FixedWindowRateLimiter
from app.schemas.common import ErrorEnvelope
from app.services.key_requests import MIN_USE_CASE_CHARS, create_or_get_pending, hash_ip

router = APIRouter(prefix="/v1/developer", tags=["developer"])

KEY_REQUEST_RATE_LIMIT_PER_HOUR = 5
RECEIVED_MESSAGE = (
    "Request received. An operator reviews requests manually during the pilot; if this address "
    "is new, your key will be sent to it."
)
ip_limiter = FixedWindowRateLimiter(window_seconds=3600)


class KeyRequestIn(BaseModel):
    email: EmailStr
    use_case: str = Field(min_length=MIN_USE_CASE_CHARS, max_length=2000)
    plan: str = Field(default="free", pattern="^(" + "|".join(SELF_SERVE_PLANS) + ")$")
    website: str = Field(default="", max_length=200, description="Honeypot; leave empty")


class KeyRequestOut(BaseModel):
    request_id: str | None = Field(
        default=None, description="Set only when this call created a new request"
    )
    email: str
    status: str
    message: str


@router.post(
    "/key-requests",
    status_code=202,
    response_model=KeyRequestOut,
    responses={422: {"model": ErrorEnvelope}, 429: {"model": ErrorEnvelope}},
    summary="Request an API key (public, rate limited)",
    description="Records a request for an operator to approve. The key is never returned here; "
    "it is delivered once by the operator (or by email when email delivery is configured).",
)
def request_key(
    body: KeyRequestIn,
    request: Request,
    db: Session = Depends(db_session),
    settings: Settings = Depends(settings_dep),
):
    ip = client_ip(request)
    enforce_ip_limit(
        ip_limiter,
        "keyreq:" + ip,
        KEY_REQUEST_RATE_LIMIT_PER_HOUR,
        "Too many key requests from this address. Try again later.",
    )
    if body.website.strip():
        # Honeypot filled in: behave like success without storing anything.
        return JSONResponse(
            status_code=202,
            content={
                "request_id": None,
                "email": body.email.lower(),
                "status": "received",
                "message": RECEIVED_MESSAGE,
            },
        )
    req, created = create_or_get_pending(
        db, body.email, body.use_case, body.plan, hash_ip(ip, settings.api_key_pepper)
    )
    return KeyRequestOut(
        request_id=str(req.id) if (created and req is not None) else None,
        email=body.email.lower(),
        status="received",
        message=RECEIVED_MESSAGE,
    )
