"""Daily international-listings job: all enabled sources, once per UTC day after a set hour.

Runs inside the poller loop (Fly/Compose) or from `scripts/ingest_markets.py --all|--loop`
(Render cron). A day's run is recorded in ingestion_runs under `markets:daily`, so whichever
process asks first does the work and the others skip.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, time, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.logging import log_event
from app.db.models import IngestionRun, utcnow
from app.services.ingestion import finish_run, start_run
from app.services.markets import canada, firds, gleif
from app.services.markets.http import MarketHttp

logger = logging.getLogger("app.jobs.markets")
DAILY_SOURCE = "markets:daily"
ORDER = ("esma_firds", "fca_firds", "tsx", "cse", "gleif")


def enabled_sources(settings: Settings) -> list[str]:
    enabled = {s.strip() for s in settings.markets_sources_enabled.split(",") if s.strip()}
    return [s for s in ORDER if s in enabled]


def run_all(db: Session, settings: Settings, http: MarketHttp | None = None) -> dict:
    """Run every enabled source in order; records a markets:daily run. Commits."""
    own = http is None
    http = http or MarketHttp(settings)
    run = start_run(db, source=DAILY_SOURCE)
    db.commit()
    results: dict = {}
    errors: list[str] = []
    try:
        for source in enabled_sources(settings):
            try:
                if source in ("esma_firds", "fca_firds"):
                    results[source] = firds.ingest_firds(db, settings, http, source)
                elif source == "gleif":
                    results[source] = gleif.enrich_issuers(db, settings, http)
                else:
                    results[source] = canada.ingest_source(db, settings, http, source)
                errors.extend(f"{source}: {e}" for e in results[source].get("errors", []))
            except Exception as exc:  # noqa: BLE001 - one source must not stop the others
                db.rollback()
                errors.append(f"{source}: {type(exc).__name__}")
                logger.exception(
                    "markets source failed", extra={"extra_fields": {"source": source}}
                )
    finally:
        if own:
            http.close()
    run = db.merge(run)
    status = "succeeded" if not errors else ("failed" if not results else "partial")
    finish_run(db, run, status, "; ".join(errors)[:2000] or None)
    db.commit()
    log_event(logger, logging.INFO, "markets daily run", status=status, sources=list(results))
    return {"status": status, "sources": results, "errors": errors}


def last_daily_run_started(db: Session) -> datetime | None:
    return db.scalar(
        select(IngestionRun.started_at)
        .where(IngestionRun.source == DAILY_SOURCE, IngestionRun.status != "failed")
        .order_by(IngestionRun.started_at.desc())
        .limit(1)
    )


def is_due(db: Session, settings: Settings, now: datetime | None = None) -> bool:
    """Due when enabled, past today's run hour (UTC), and not yet run today."""
    if not settings.markets_daily_enabled or not enabled_sources(settings):
        return False
    now = now or utcnow()
    if now.hour < settings.markets_daily_hour_utc:
        return False
    last = last_daily_run_started(db)
    return last is None or last.astimezone(UTC).date() < now.date()


def maybe_run(
    db: Session, settings: Settings, now: datetime | None = None, http=None
) -> dict | None:
    if not is_due(db, settings, now):
        return None
    return run_all(db, settings, http=http)


def seconds_until_next_run(settings: Settings, now: datetime | None = None) -> int:
    now = now or utcnow()
    target = datetime.combine(now.date(), time(hour=settings.markets_daily_hour_utc), tzinfo=UTC)
    if target <= now:
        target += timedelta(days=1)
    return max(60, int((target - now).total_seconds()))
