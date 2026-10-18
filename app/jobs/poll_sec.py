"""Scheduled SEC polling job: refresh watched companies, then deliver pending notifications.

Single-run guard: PostgreSQL advisory lock (pg_try_advisory_lock) when available; a local
file lock otherwise. Safe to run from cron every INGESTION_POLL_INTERVAL_SECONDS.
"""

from __future__ import annotations

import contextlib
import fcntl
import logging
import time
from collections.abc import Iterator
from pathlib import Path

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.logging import log_event
from app.db.models import Company, CompanyWatch, utcnow
from app.services import quality, universe
from app.services.ingestion import finish_run, start_run
from app.services.notifications import deliver_pending
from app.services.sec_client import SecClient

logger = logging.getLogger("app.jobs.poll")
ADVISORY_LOCK_KEY = 7_201_349_001


@contextlib.contextmanager
def single_run_guard(db: Session, lock_file: str = ".poll_sec.lock") -> Iterator[bool]:
    """Yield True if this process holds the poll lock, False if another run is active."""
    if db.bind is not None and db.bind.dialect.name == "postgresql":
        acquired = bool(
            db.execute(text("SELECT pg_try_advisory_lock(:k)"), {"k": ADVISORY_LOCK_KEY}).scalar()
        )
        try:
            yield acquired
        finally:
            if acquired:
                db.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": ADVISORY_LOCK_KEY})
                db.commit()
        return
    path = Path(lock_file)
    fh = path.open("a+")
    try:
        try:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            acquired = True
        except OSError:
            acquired = False
        yield acquired
    finally:
        if acquired:
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
        fh.close()


def watched_ciks(db: Session, include_all_companies: bool = False) -> list[str]:
    if include_all_companies:
        return list(db.scalars(select(Company.cik).where(Company.last_processed_at.is_not(None))))
    return list(
        db.scalars(select(CompanyWatch.cik).where(CompanyWatch.is_active.is_(True)).distinct())
    )


def run_once(
    db: Session,
    settings: Settings,
    client: SecClient | None = None,
    include_all_companies: bool = False,
    sender=None,
    include_universe: bool = True,
) -> dict:
    with single_run_guard(db) as acquired:
        if not acquired:
            log_event(logger, logging.INFO, "poll skipped: another run holds the lock")
            return {"skipped": True}
        own_client = client is None
        client = client or SecClient(settings)
        run = start_run(db, source="sec:poll")
        db.commit()
        ciks = watched_ciks(db, include_all_companies)
        summary = {"companies": len(ciks), "succeeded": 0, "failed": 0, "notifications_created": 0}
        errors: list[str] = []
        try:
            for cik in ciks:
                now = utcnow()
                member = universe.ensure_member(db, cik, source="watch", now=now)
                db.commit()
                ok, error = universe.ingest_member(db, settings, client, member, run, now)
                run = db.merge(run)
                if ok:
                    summary["succeeded"] += 1
                    summary["notifications_created"] += (
                        universe.last_result.notifications_created if universe.last_result else 0
                    )
                else:
                    summary["failed"] += 1
                    errors.append(f"{cik}: {error}")
            if include_universe:
                summary["universe"] = universe.bulk_ingest(db, settings, client, run=run)
                run = db.merge(run)
                errors.extend(summary["universe"].get("errors", []))
            if not errors:
                status = "succeeded"
            elif summary["succeeded"] == 0 and ciks:
                status = "failed"
            else:
                status = "partial"
            finish_run(db, run, status, "; ".join(errors)[:2000] or None)
            db.commit()
            summary["deliveries"] = deliver_pending(db, settings, sender=sender)
            snap = quality.take_snapshot(db, settings, run_id=run.id)
            db.commit()
            summary["snapshot_id"] = str(snap.id)
        finally:
            if own_client:
                client.close()
        log_event(
            logger,
            logging.INFO,
            "poll finished",
            **{k: v for k, v in summary.items() if k != "deliveries"},
        )
        return summary


def run_forever(session_maker, settings: Settings, include_all_companies: bool = False) -> None:
    while True:
        db = session_maker()
        try:
            run_once(db, settings, include_all_companies=include_all_companies)
        except Exception:  # noqa: BLE001
            logger.exception("poll iteration crashed")
        finally:
            db.close()
        time.sleep(settings.ingestion_poll_interval_seconds)
