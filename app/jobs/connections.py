"""Daily upkeep of the connections graph (ADR 0011), run by the poller once per UTC day.

- Loads any quarterly insider data set newer than the latest one loaded (one request to the
  SEC's data set page each day; a download only when a new quarter appears).
- Rereads the showcase companies' exhibit 21, 13D/G filings and newest Forms 4, so the public
  demo, which never fetches, stays current.
"""

from __future__ import annotations

import logging
from datetime import date
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.logging import log_event
from app.db.models import InsiderDataset
from app.services import insiders
from app.services.sec_client import SecClient, SecClientError

logger = logging.getLogger("app.jobs.connections")


def load_new_datasets(db: Session, settings: Settings, sec: SecClient) -> list[dict]:
    newest = db.scalar(select(func.max(InsiderDataset.quarter)))
    available = insiders.discover_datasets(sec)
    wanted = [q for q in available if newest is None or q > newest]
    if newest is None:
        wanted = wanted[-4:]  # a first run takes the last year; the script loads more
    folder = Path(settings.sec_bulk_dir) / "insiders"
    folder.mkdir(parents=True, exist_ok=True)
    out = []
    for q in wanted:
        dest = folder / f"{q}_form345.zip"
        sec.download_file(available[q], dest)
        out.append(insiders.load_dataset(db, dest, q))
    return out


def run(db: Session, settings: Settings, sec: SecClient | None = None) -> dict:
    from app.api.routes_graph import refresh_sources
    from app.services.public import showcase_ciks

    own = sec is None
    sec = sec or SecClient(settings)
    out: dict = {"datasets": [], "companies": 0, "errors": 0}
    try:
        try:
            out["datasets"] = load_new_datasets(db, settings, sec)
        except SecClientError as exc:
            db.rollback()
            out["errors"] += 1
            log_event(logger, logging.WARNING, "insider data sets unavailable", error=str(exc))
        for cik in showcase_ciks(db, settings)[0]:
            res = refresh_sources(db, sec, cik)
            out["companies"] += 1
            out["errors"] += sum(1 for v in res.values() if "error" in v)
    finally:
        if own:
            sec.close()
    log_event(logger, logging.INFO, "connections daily", **{k: v for k, v in out.items()
                                                            if k != "datasets"},
              datasets=len(out["datasets"]))  # fmt: skip
    return out


def maybe_run(db: Session, settings: Settings, last_day: date | None, today: date) -> date | None:
    """Runs on the first poll of each UTC day; returns the day it last ran."""
    if not settings.connections_daily_enabled or last_day == today:
        return last_day
    run(db, settings)
    return today
