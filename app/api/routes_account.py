"""Accounts in the browser (GH #15): sign in by emailed link, then manage keys, usage and theme.

These routes use a session cookie, not an API key. The cookie is HttpOnly, SameSite=Lax and
Secure in production; changes also require a same-origin request, so another site cannot act
for a signed-in visitor.
"""

from __future__ import annotations

import uuid
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.orm import Session

from app.api.dependencies import db_session, enforce_ip_limit, ip_key, settings_dep
from app.core.config import Settings, plan_limits
from app.core.errors import APIError
from app.core.rate_limits import FixedWindowRateLimiter
from app.db.models import Account, AccountSession
from app.schemas.account import (
    AccountKey,
    AccountOut,
    AccountUpdate,
    KeyCreate,
    KeyCreated,
    SignInRequest,
    SignInSent,
    VerifyRequest,
)
from app.schemas.common import ErrorEnvelope
from app.services import accounts
from app.services.api_keys import create_key_record, revoke_key
from app.services.email_adapter import can_send, send_sign_in_email
from app.services.key_requests import hash_ip
from app.services.usage import requests_this_month

# Cookie-only endpoints for the /account/ page: site-internal, so not in the public reference.
router = APIRouter(prefix="/v1/account", tags=["account"], include_in_schema=False)

SESSION_COOKIE = "prv_session"
SENT = (
    "If that address can sign in, a link is on its way. It works once, for a short time. "
    "Check your spam folder if it does not arrive in a few minutes."
)
ip_limiter = FixedWindowRateLimiter(window_seconds=3600, name="sign-in-ip")
email_limiter = FixedWindowRateLimiter(window_seconds=3600, name="sign-in-email")
_ERRORS = {
    401: {"model": ErrorEnvelope},
    403: {"model": ErrorEnvelope},
    404: {"model": ErrorEnvelope},
    422: {"model": ErrorEnvelope},
    429: {"model": ErrorEnvelope},
    503: {"model": ErrorEnvelope},
}


def _same_origin(request: Request) -> None:
    """Refuse a cookie-authenticated change sent from another site."""
    origin = request.headers.get("origin") or request.headers.get("referer")
    if origin and urlsplit(origin).netloc != request.url.netloc:
        raise APIError(403, "forbidden", "Requests must come from this site.")


def _signed_in(request: Request, db: Session = Depends(db_session)):
    found = accounts.session_account(db, request.cookies.get(SESSION_COOKIE))
    if found is None:
        raise APIError(401, "not_signed_in", "Sign in to see your account.")
    db.commit()  # last_seen_at
    return found


def _base_url(request: Request, settings: Settings) -> str:
    return (settings.public_base_url or str(request.base_url)).rstrip("/")


def _account_out(db: Session, settings: Settings, account: Account) -> AccountOut:
    keys = accounts.account_keys(db, account)
    out_keys = []
    total = 0
    for k in keys:
        used = requests_this_month(db, k.id) if k.is_active else 0
        total += used
        item = AccountKey.model_validate(k)
        item.requests_this_month = used
        out_keys.append(item)
    plan = accounts.best_plan(keys)
    return AccountOut(
        email=account.email,
        created_at=account.created_at,
        plan=plan,
        ui_theme=account.ui_theme or "dark",
        monthly_request_quota=plan_limits(plan, settings)["monthly_request_quota"],
        requests_this_month=total,
        max_active_keys=settings.account_max_active_keys,
        keys=out_keys,
    )


@router.post(
    "/sign-in",
    response_model=SignInSent,
    status_code=202,
    responses=_ERRORS,
    summary="Email a one-time sign-in link (also signs up)",
)
def sign_in(
    body: SignInRequest,
    request: Request,
    db: Session = Depends(db_session),
    settings: Settings = Depends(settings_dep),
):
    _same_origin(request)
    if not can_send(settings):
        raise APIError(
            503,
            "email_delivery_not_configured",
            "Sign-in by email is not available on this deployment yet. Request a key instead.",
        )
    email = accounts.normalize_email(body.email)
    enforce_ip_limit(
        ip_limiter,
        "sign-in-ip:" + ip_key(request),
        settings.sign_in_per_ip_per_hour,
        "Too many sign-in requests from this address. Try again later.",
    )
    # Over the per-email limit, answer exactly as if a link was sent: no enumeration, no flood.
    if email_limiter.check(
        "sign-in-email:" + (hash_ip(email, settings.api_key_pepper) or ""),
        settings.sign_in_per_email_per_hour,
    ).allowed:
        raw = accounts.create_sign_in_token(db, settings, email)
        db.commit()
        link = f"{_base_url(request, settings)}/account/verify/#token={raw}"
        send_sign_in_email(settings, email, link, settings.sign_in_link_minutes)
    return SignInSent(message=SENT)


@router.post("/verify", response_model=AccountOut, responses=_ERRORS, summary="Open a sign-in link")
def verify(
    body: VerifyRequest,
    request: Request,
    response: Response,
    db: Session = Depends(db_session),
    settings: Settings = Depends(settings_dep),
):
    _same_origin(request)
    account = accounts.redeem_sign_in_token(db, body.token)
    if account is None:
        db.rollback()
        raise APIError(
            401,
            "invalid_link",
            "This sign-in link has expired or was already used. Ask for a new one.",
        )
    raw = accounts.start_session(db, settings, account)
    db.commit()
    response.set_cookie(
        SESSION_COOKIE,
        raw,
        max_age=settings.account_session_days * 86400,
        httponly=True,
        secure=settings.is_production or request.url.scheme == "https",
        samesite="lax",
        path="/",
    )
    return _account_out(db, settings, account)


@router.get("", response_model=AccountOut, responses=_ERRORS, summary="Your account")
def me(
    found=Depends(_signed_in),
    db: Session = Depends(db_session),
    settings: Settings = Depends(settings_dep),
):
    return _account_out(db, settings, found[0])


@router.patch("", response_model=AccountOut, responses=_ERRORS, summary="Save your theme")
def update_me(
    body: AccountUpdate,
    request: Request,
    found=Depends(_signed_in),
    db: Session = Depends(db_session),
    settings: Settings = Depends(settings_dep),
):
    _same_origin(request)
    account = db.get(Account, found[0].id)
    accounts.set_theme(db, account, None if body.ui_theme == "dark" else body.ui_theme)
    db.commit()
    return _account_out(db, settings, account)


@router.post(
    "/keys",
    response_model=KeyCreated,
    status_code=201,
    responses=_ERRORS,
    summary="Create an API key",
)
def create_key(
    body: KeyCreate,
    request: Request,
    found=Depends(_signed_in),
    db: Session = Depends(db_session),
    settings: Settings = Depends(settings_dep),
):
    _same_origin(request)
    account = found[0]
    active = [k for k in accounts.account_keys(db, account) if k.is_active]
    # keys per account follow the account's best plan (G-01), never above the site-wide cap
    max_keys = min(
        settings.account_max_active_keys,
        plan_limits(accounts.best_plan(active), settings)["max_keys"],
    )
    if len(active) >= max_keys:
        raise APIError(
            422,
            "key_limit_reached",
            f"At most {max_keys} active keys on this plan. Revoke one first.",
        )
    key, raw = create_key_record(
        db, settings, account.email, "free", body.label, actor=f"account:{account.id}"
    )
    key.ui_theme = account.ui_theme
    db.commit()
    return KeyCreated(**AccountKey.model_validate(key).model_dump(), api_key=raw)


@router.delete(
    "/keys/{key_id}", response_model=AccountKey, responses=_ERRORS, summary="Revoke an API key"
)
def delete_key(
    key_id: uuid.UUID,
    request: Request,
    found=Depends(_signed_in),
    db: Session = Depends(db_session),
):
    _same_origin(request)
    key = accounts.owned_key(db, found[0], key_id)
    if key is None:
        raise APIError(404, "api_key_not_found", "No such key on your account.")
    revoke_key(db, key, actor=f"account:{found[0].id}")
    db.commit()
    return AccountKey.model_validate(key)


@router.post("/sign-out", status_code=204, responses=_ERRORS, summary="Sign out this browser")
def sign_out(request: Request, response: Response, db: Session = Depends(db_session)):
    _same_origin(request)
    found = accounts.session_account(db, request.cookies.get(SESSION_COOKIE))
    if found is not None:
        accounts.end_session(db, db.get(AccountSession, found[1].id))
        db.commit()
    response.delete_cookie(SESSION_COOKIE, path="/")
    response.status_code = 204
    return response


@router.post(
    "/sign-out-everywhere",
    status_code=204,
    responses=_ERRORS,
    summary="Sign out every browser",
)
def sign_out_everywhere(
    request: Request,
    response: Response,
    found=Depends(_signed_in),
    db: Session = Depends(db_session),
):
    _same_origin(request)
    accounts.end_all_sessions(db, db.get(Account, found[0].id))
    db.commit()
    response.delete_cookie(SESSION_COOKIE, path="/")
    response.status_code = 204
    return response
