"""Hourly filings tracker (ADR 0012), run from the poller loop or scripts/track_filings.py."""

from __future__ import annotations

import logging
from datetime import datetime

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.logging import log_event
from app.services import filings_tracker
from app.services.ingestion import finish_run, start_run
from app.services.sec_client import SecClient

logger = logging.getLogger("app.jobs.filings_tracker")


def run(db: Session, settings: Settings, client: SecClient | None = None) -> dict:
    own = client is None
    client = client or SecClient(settings)
    run_row = start_run(db, source="sec:tracker")
    db.commit()
    try:
        summary = filings_tracker.run_once(db, settings, client, run=run_row)
        parts = ("search", "latest", "daily_index")
        errors = [f"{k}: {summary[k]['error']}" for k in parts if summary.get(k, {}).get("error")]
        status = "partial" if errors or summary["failed"] else "succeeded"
        finish_run(db, db.merge(run_row), status, "; ".join(errors)[:2000] or None)
        db.commit()
        return summary
    except Exception as exc:  # noqa: BLE001 - recorded on the run, then raised
        db.rollback()
        finish_run(db, db.merge(run_row), "failed", str(exc)[:2000])
        db.commit()
        raise
    finally:
        if own:
            client.close()


def maybe_run(
    db: Session, settings: Settings, last_at: datetime | None, now: datetime
) -> datetime | None:
    """Runs when `filings_tracker_interval_seconds` have passed; returns when it last ran."""
    if not settings.filings_tracker_enabled:
        return last_at
    if last_at and (now - last_at).total_seconds() < settings.filings_tracker_interval_seconds:
        return last_at
    try:
        run(db, settings)
    except Exception:  # noqa: BLE001 - one failed run never stops the poller
        logger.exception("filings tracker failed")
        log_event(logger, logging.WARNING, "filings tracker run failed")
    return now
