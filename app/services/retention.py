"""Retention purges for request logs, finished deliveries, used sign-in links and ended sessions
(see docs/data-rights.md and the privacy page)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, or_
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.rate_limits import KEEP_SECONDS
from app.db.models import (
    AccountSession,
    ApiUsage,
    NotificationDelivery,
    RateLimitCounter,
    SignInToken,
)

# A sign-in link is kept a day past its expiry; an ended session a week, for support questions.
SIGN_IN_KEEP = timedelta(days=1)
SESSION_KEEP = timedelta(days=7)


def purge(db: Session, settings: Settings, now: datetime | None = None) -> dict[str, int]:
    now = now or datetime.now(UTC)
    usage_cutoff = now - timedelta(days=settings.usage_retention_days)
    delivery_cutoff = now - timedelta(days=settings.delivery_retention_days)
    usage_deleted = db.execute(delete(ApiUsage).where(ApiUsage.occurred_at < usage_cutoff)).rowcount
    deliveries_deleted = db.execute(
        delete(NotificationDelivery).where(
            NotificationDelivery.status.in_(["delivered", "failed"]),
            NotificationDelivery.created_at < delivery_cutoff,
        )
    ).rowcount
    counters_deleted = db.execute(
        delete(RateLimitCounter).where(
            RateLimitCounter.window_start < int(now.timestamp()) - KEEP_SECONDS
        )
    ).rowcount
    links_deleted = db.execute(
        delete(SignInToken).where(SignInToken.expires_at < now - SIGN_IN_KEEP)
    ).rowcount
    sessions_deleted = db.execute(
        delete(AccountSession).where(
            or_(
                AccountSession.expires_at < now - SESSION_KEEP,
                AccountSession.revoked_at < now - SESSION_KEEP,
            )
        )
    ).rowcount
    db.commit()
    return {
        "api_usage": int(usage_deleted),
        "notification_deliveries": int(deliveries_deleted),
        "rate_limit_counters": int(counters_deleted),
        "sign_in_tokens": int(links_deleted),
        "account_sessions": int(sessions_deleted),
    }
