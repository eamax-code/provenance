"""Accounts (GH #15): sign in with a one-time link sent by email, then a session cookie.

Signing up and signing in are one flow. Asking for a link answers the same way whether or not
the email has an account, so the form cannot be used to find out who is a customer. The account
is created when its first link is opened, which proves the address. Keys belong to an account by
email, so keys an operator issued before accounts existed appear once their owner signs in.
Tokens and session ids are random; only their hashes are stored.
"""

from __future__ import annotations

import secrets
import uuid
from datetime import datetime, timedelta

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.plans import PLAN_RANK
from app.core.security import hash_secret
from app.db.models import Account, AccountSession, ApiKey, AuditEvent, SignInToken, utcnow


def normalize_email(email: str) -> str:
    return email.strip().lower()


def create_sign_in_token(db: Session, settings: Settings, email: str) -> str:
    """A new link token for this email. The caller sends it; nothing is stored in clear."""
    raw = secrets.token_urlsafe(32)
    now = utcnow()
    db.add(
        SignInToken(
            email=normalize_email(email),
            token_hash=hash_secret(raw),
            created_at=now,
            expires_at=now + timedelta(minutes=settings.sign_in_link_minutes),
        )
    )
    db.flush()
    return raw


def redeem_sign_in_token(db: Session, raw: str, now: datetime | None = None) -> Account | None:
    """Use a link once. Returns the account (created on first use), or None if the link is
    unknown, used or expired."""
    now = now or utcnow()
    token = db.scalar(select(SignInToken).where(SignInToken.token_hash == hash_secret(raw)))
    if token is None or token.used_at is not None or token.expires_at <= now:
        return None
    # Mark used in the same statement that checks it, so two clicks cannot both succeed.
    claimed = db.execute(
        update(SignInToken)
        .where(SignInToken.id == token.id, SignInToken.used_at.is_(None))
        .values(used_at=now)
    ).rowcount
    if not claimed:
        return None
    account = db.scalar(select(Account).where(Account.email == token.email))
    if account is None:
        account = Account(email=token.email, created_at=now)
        db.add(account)
        db.flush()
        _audit(db, account, "account.created", now)
    account.last_sign_in_at = now
    _audit(db, account, "account.signed_in", now)
    db.flush()
    return account


def start_session(db: Session, settings: Settings, account: Account) -> str:
    raw = secrets.token_urlsafe(32)
    now = utcnow()
    db.add(
        AccountSession(
            account_id=account.id,
            token_hash=hash_secret(raw),
            created_at=now,
            expires_at=now + timedelta(days=settings.account_session_days),
            last_seen_at=now,
        )
    )
    db.flush()
    return raw


def session_account(db: Session, raw: str | None) -> tuple[Account, AccountSession] | None:
    if not raw:
        return None
    now = utcnow()
    session = db.scalar(select(AccountSession).where(AccountSession.token_hash == hash_secret(raw)))
    if session is None or session.revoked_at is not None or session.expires_at <= now:
        return None
    account = db.get(Account, session.account_id)
    if account is None:
        return None
    if session.last_seen_at is None or now - session.last_seen_at > timedelta(minutes=5):
        session.last_seen_at = now
        db.flush()
    return account, session


def end_session(db: Session, session: AccountSession) -> None:
    session.revoked_at = utcnow()
    db.flush()


def end_all_sessions(db: Session, account: Account) -> int:
    now = utcnow()
    count = db.execute(
        update(AccountSession)
        .where(AccountSession.account_id == account.id, AccountSession.revoked_at.is_(None))
        .values(revoked_at=now)
    ).rowcount
    _audit(db, account, "account.signed_out_everywhere", now)
    db.flush()
    return count


def account_keys(db: Session, account: Account) -> list[ApiKey]:
    """Every key issued to this email, newest first, including operator-issued ones."""
    return list(
        db.scalars(
            select(ApiKey)
            .where(func.lower(ApiKey.owner_email) == account.email)
            .order_by(ApiKey.created_at.desc())
        )
    )


def best_plan(keys: list[ApiKey]) -> str:
    plans = [k.plan for k in keys if k.is_active] or ["free"]
    return max(plans, key=lambda p: PLAN_RANK.index(p) if p in PLAN_RANK else 0)


def owned_key(db: Session, account: Account, key_id: uuid.UUID) -> ApiKey | None:
    key = db.get(ApiKey, key_id)
    if key is None or key.owner_email.lower() != account.email:
        return None
    return key


def set_theme(db: Session, account: Account, theme: str | None) -> None:
    """The account's theme, copied to its keys so chat and the Explorer pick it up too."""
    account.ui_theme = theme
    for key in account_keys(db, account):
        if key.is_active:
            key.ui_theme = theme
    db.flush()


def _audit(db: Session, account: Account, action: str, now: datetime) -> None:
    db.add(
        AuditEvent(
            actor=f"account:{account.id}",
            action=action,
            subject_type="account",
            subject_id=str(account.id),
            occurred_at=now,
        )
    )
