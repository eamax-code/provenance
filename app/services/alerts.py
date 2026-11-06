"""Operator alerts posted to a chat webhook (ticket 12; see docs/operations.md).

After each poll the poller checks the conditions operations.md asks to alert on and, if
ALERT_WEBHOOK_URL is set, posts one message per condition that has newly started, then again at
most every ALERT_REPEAT_SECONDS while it lasts. The body carries both "text" (Slack) and "content"
(Discord), so either accepts it. Nothing is sent when the URL is unset; the conditions are still
logged.
"""

from __future__ import annotations

import logging
import time

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.logging import log_event
from app.db.models import DataQualitySnapshot, IngestionRun

logger = logging.getLogger("app.alerts")
FAILED_RUNS_IN_A_ROW = 2
PENDING_DELIVERY_SECONDS = 3600
LATENCY_SLACK_SECONDS = 600
_last_sent: dict[str, float] = {}  # condition -> when it was last posted (this process)


def conditions(db: Session, settings: Settings, snap: DataQualitySnapshot | None) -> dict[str, str]:
    """The alert conditions holding now, as {key: message}."""
    found: dict[str, str] = {}
    recent = db.scalars(
        select(IngestionRun.status)
        .where(IngestionRun.source == "sec:poll", IngestionRun.status != "running")
        .order_by(IngestionRun.started_at.desc())
        .limit(FAILED_RUNS_IN_A_ROW)
    ).all()
    if len(recent) == FAILED_RUNS_IN_A_ROW and all(s == "failed" for s in recent):
        found["ingestion_failing"] = (
            f"The last {FAILED_RUNS_IN_A_ROW} SEC poll runs failed. Check ingestion_runs."
            "error_summary and the SEC User-Agent."
        )
    if snap is not None:
        age = snap.oldest_pending_age_seconds
        if age is not None and age > PENDING_DELIVERY_SECONDS:
            found["delivery_backlog"] = (
                f"{snap.pending_deliveries} webhook or email deliveries are waiting; the oldest "
                f"for {age // 60} minutes."
            )
        p95 = snap.detect_to_process_p95_s
        allowed = settings.ingestion_poll_interval_seconds + LATENCY_SLACK_SECONDS
        if p95 is not None and p95 > allowed:
            found["slow_processing"] = (
                f"Filings take {p95 // 60} minutes from detection to processing (95th percentile, "
                f"last 24 hours), longer than the poll interval allows."
            )
        if snap.duplicate_filings:
            found["duplicate_filings"] = f"{snap.duplicate_filings} duplicate filings recorded."
    return found


def check_and_notify(
    db: Session, settings: Settings, snap: DataQualitySnapshot | None, http=None, now=None
) -> list[str]:
    """Post the conditions that are due; returns the keys posted."""
    now = time.time() if now is None else now
    found = conditions(db, settings, snap)
    for key in list(_last_sent):
        if key not in found:  # resolved: a new occurrence alerts again at once
            del _last_sent[key]
    due = [k for k in found if now - _last_sent.get(k, -1e12) >= settings.alert_repeat_seconds]
    for key in due:
        log_event(logger, logging.WARNING, "alert", condition=key, message=found[key])
    if not due or not settings.alert_webhook_url:
        for key in due:
            _last_sent[key] = now
        return []
    text = "\n".join(f"Provenance alert ({settings.app_env}): {found[k]}" for k in due)
    client = http or httpx.Client(timeout=settings.webhook_timeout_seconds)
    try:
        client.post(settings.alert_webhook_url, json={"text": text, "content": text})
    except httpx.HTTPError as exc:
        log_event(logger, logging.WARNING, "alert post failed", error=type(exc).__name__)
        return []
    finally:
        if http is None:
            client.close()
    for key in due:
        _last_sent[key] = now
    return due


def reset() -> None:
    _last_sent.clear()
