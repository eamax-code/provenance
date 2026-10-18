"""Self-serve key requests: record, dedupe, approve (issue key once), reject."""

from __future__ import annotations

import hashlib
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db.models import ApiKey, AuditEvent, KeyRequest, utcnow
from app.services.api_keys import create_key_record

MIN_USE_CASE_CHARS = 12


def hash_ip(ip: str | None, pepper: str) -> str | None:
    if not ip:
        return None
    return hashlib.sha256(f"{pepper}:{ip}".encode()).hexdigest()[:32]


def create_or_get_pending(
    db: Session, email: str, use_case: str, plan: str, client_ip_hash: str | None
) -> tuple[KeyRequest | None, bool]:
    """Return (request_or_None, created).

    Nothing new is stored when a pending request or an active key already exists for the
    email; callers answer identically in both cases so the endpoint cannot be used to probe
    which addresses are known.
    """
    email = email.strip().lower()
    existing = db.scalar(
        select(KeyRequest).where(KeyRequest.email == email, KeyRequest.status == "pending")
    )
    if existing is not None:
        return existing, False
    active_key = db.scalar(
        select(ApiKey.id).where(ApiKey.owner_email == email, ApiKey.is_active.is_(True))
    )
    if active_key is not None:
        return None, False
    req = KeyRequest(
        email=email,
        use_case=use_case.strip()[:2000],
        requested_plan=plan,
        status="pending",
        client_ip_hash=client_ip_hash,
        created_at=utcnow(),
    )
    db.add(req)
    db.flush()
    db.add(
        AuditEvent(
            actor="public",
            action="key_request.created",
            subject_type="key_request",
            subject_id=str(req.id),
            occurred_at=req.created_at,
        )
    )
    db.commit()
    return req, True


def list_pending(db: Session) -> list[KeyRequest]:
    return list(
        db.scalars(
            select(KeyRequest).where(KeyRequest.status == "pending").order_by(KeyRequest.created_at)
        )
    )


def approve_request(
    db: Session,
    settings: Settings,
    request_id: uuid.UUID,
    plan: str = "free",
    actor: str = "operator",
    delivered_via: str = "operator",
) -> tuple[ApiKey, str]:
    req = db.get(KeyRequest, request_id)
    if req is None:
        raise ValueError("key request not found")
    if req.status != "pending":
        raise ValueError(f"key request is already {req.status}")
    # Mark the request first, then issue the key, all in the caller's transaction, so a failure
    # anywhere leaves neither an orphaned key nor a re-approvable request.
    req.status = "approved"
    req.approved_at = utcnow()
    req.key_delivered_via = delivered_via
    key, raw = create_key_record(db, settings, req.email, plan, label="self-serve", actor=actor)
    req.approved_key_id = key.id
    db.add(
        AuditEvent(
            actor=actor,
            action="key_request.approved",
            subject_type="key_request",
            subject_id=str(req.id),
            occurred_at=req.approved_at,
        )
    )
    db.flush()
    return key, raw


def reject_request(
    db: Session, request_id: uuid.UUID, reason: str, actor: str = "operator"
) -> None:
    req = db.get(KeyRequest, request_id)
    if req is None or req.status != "pending":
        raise ValueError("key request not found or not pending")
    req.status = "rejected"
    req.rejected_reason = reason[:500]
    db.add(
        AuditEvent(
            actor=actor,
            action="key_request.rejected",
            subject_type="key_request",
            subject_id=str(req.id),
            occurred_at=utcnow(),
        )
    )
    db.flush()
