"""Public, cached service statistics. Nothing here is per-customer or secret."""

from __future__ import annotations

import threading
import time
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.timeutil import iso_z
from app.db.models import (
    Company,
    CompanyWatch,
    Filing,
    FinancialFact,
    IngestionRun,
    NotificationDelivery,
)
from app.services.fact_normalizer import MAPPING_VERSION
from app.services.quality import latest_snapshot, snapshot_to_dict

CACHE_TTL_SECONDS = 30

_lock = threading.Lock()
_cached: tuple[float, dict] | None = None


def reset_cache() -> None:
    global _cached
    with _lock:
        _cached = None


_iso = iso_z


def compute_stats(db: Session, settings: Settings, now: datetime | None = None) -> dict:
    now = now or datetime.now(UTC)
    companies_known = int(db.scalar(select(func.count(Company.id))) or 0)
    companies_ingested = int(
        db.scalar(select(func.count(Company.id)).where(Company.last_processed_at.is_not(None))) or 0
    )
    companies_with_errors = int(
        db.scalar(select(func.count(Company.id)).where(Company.last_fetch_error.is_not(None))) or 0
    )
    filings_total = int(db.scalar(select(func.count(Filing.id))) or 0)
    filings_with_accepted = int(
        db.scalar(select(func.count(Filing.id)).where(Filing.accepted_at.is_not(None))) or 0
    )
    facts_total = int(db.scalar(select(func.count(FinancialFact.id))) or 0)
    by_quality = {
        status: int(count)
        for status, count in db.execute(
            select(FinancialFact.quality_status, func.count(FinancialFact.id)).group_by(
                FinancialFact.quality_status
            )
        ).all()
    }
    by_metric = {
        metric: int(count)
        for metric, count in db.execute(
            select(FinancialFact.metric, func.count(FinancialFact.id)).group_by(
                FinancialFact.metric
            )
        ).all()
    }
    last_fetch = db.scalar(select(func.max(Company.last_successful_fetch_at)))
    latest_detected = db.scalar(select(func.max(Filing.first_detected_at)))
    latest_filing_date = db.scalar(select(func.max(Filing.filing_date)))
    last_run = db.scalar(select(IngestionRun).order_by(IngestionRun.started_at.desc()).limit(1))
    pending = int(
        db.scalar(
            select(func.count(NotificationDelivery.id)).where(
                NotificationDelivery.status.in_(["pending", "retrying"])
            )
        )
        or 0
    )
    delivered = int(
        db.scalar(
            select(func.count(NotificationDelivery.id)).where(
                NotificationDelivery.status == "delivered"
            )
        )
        or 0
    )
    failed = int(
        db.scalar(
            select(func.count(NotificationDelivery.id)).where(
                NotificationDelivery.status == "failed"
            )
        )
        or 0
    )
    watches = int(
        db.scalar(select(func.count(CompanyWatch.id)).where(CompanyWatch.is_active.is_(True))) or 0
    )
    stale_after = settings.freshness_stale_after_seconds
    fetch_age = int((now - last_fetch).total_seconds()) if last_fetch else None
    if last_fetch is None:
        health = "empty"
    elif fetch_age is not None and fetch_age > stale_after:
        health = "stale"
    elif last_run is not None and last_run.status == "failed":
        health = "degraded"
    else:
        health = "ok"

    return {
        "service": {"name": settings.app_name, "version": settings.app_version, "health": health},
        "companies": {
            "known": companies_known,
            "ingested": companies_ingested,
            "with_fetch_errors": companies_with_errors,
        },
        "filings": {
            "total": filings_total,
            "with_acceptance_timestamp": filings_with_accepted,
            "latest_filing_date": latest_filing_date.isoformat() if latest_filing_date else None,
        },
        "facts": {"total": facts_total, "by_quality": by_quality, "by_metric": by_metric},
        "freshness": {
            "last_successful_fetch_at": _iso(last_fetch),
            "last_successful_fetch_age_seconds": fetch_age,
            "latest_filing_detected_at": _iso(latest_detected),
            "stale_after_seconds": stale_after,
            "poll_interval_seconds": settings.ingestion_poll_interval_seconds,
        },
        "ingestion": {
            "last_run_status": last_run.status if last_run else None,
            "last_run_started_at": _iso(last_run.started_at) if last_run else None,
            "last_run_finished_at": _iso(last_run.finished_at) if last_run else None,
            "last_run_error_count": last_run.error_count if last_run else None,
        },
        "notifications": {
            "active_watches": watches,
            "pending_deliveries": pending,
            "delivered_total": delivered,
            "failed_total": failed,
        },
        "quality_snapshot": snapshot_to_dict(snap) if (snap := latest_snapshot(db)) else None,
        "mapping_version": MAPPING_VERSION,
        "generated_at": _iso(now),
        "cache_ttl_seconds": CACHE_TTL_SECONDS,
        "source": "SEC EDGAR",
        "disclaimer": (
            "Independent service, not affiliated with or endorsed by the SEC. Counts reflect what "
            "this service has ingested, not the SEC universe."
        ),
    }


def cached_stats(db: Session, settings: Settings) -> dict:
    global _cached
    with _lock:
        if _cached and time.monotonic() - _cached[0] < CACHE_TTL_SECONDS:
            return _cached[1]
    data = compute_stats(db, settings)
    with _lock:
        _cached = (time.monotonic(), data)
    return data
