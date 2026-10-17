"""Retention purges for request logs and finished deliveries (see docs/data-rights.md)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db.models import ApiUsage, NotificationDelivery


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
    db.commit()
    return {"api_usage": int(usage_deleted), "notification_deliveries": int(deliveries_deleted)}
