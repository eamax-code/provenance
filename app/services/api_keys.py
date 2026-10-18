"""API key issuance. Flushes but never commits: the caller owns the transaction."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.security import generate_api_key
from app.db.models import ApiKey, AuditEvent, utcnow


def create_key_record(
    db: Session, settings: Settings, owner_email: str, plan: str, label: str | None, actor: str
) -> tuple[ApiKey, str]:
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
    db.flush()
    return key, generated.raw_key


def revoke_key(db: Session, key: ApiKey, actor: str) -> None:
    if not key.is_active:
        return
    now = utcnow()
    key.is_active = False
    key.revoked_at = now
    db.add(
        AuditEvent(
            actor=actor,
            action="api_key.revoked",
            subject_type="api_key",
            subject_id=str(key.id),
            occurred_at=now,
        )
    )
    db.flush()
