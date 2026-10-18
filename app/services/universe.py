"""Universe management: which CIKs this deployment keeps ingested, and budgeted bulk ingestion.

State lives in `universe_members`, so a run interrupted by a budget, a crash or an SEC outage
resumes where it stopped. Failures back off exponentially and disable a member after
UNIVERSE_MAX_CONSECUTIVE_FAILURES.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.logging import log_event
from app.db.models import IngestionRun, UniverseMember, utcnow
from app.services.ingestion import (
    finish_run,
    ingest_company,
    parse_ticker_exchange,
    start_run,
)
from app.services.quality import take_snapshot
from app.services.sec_client import SecClient, SecClientError, normalize_cik

logger = logging.getLogger("app.universe")

REQUESTS_PER_COMPANY = 2  # submissions + company facts; history pages add one each
last_result = None  # IngestResult of the most recent ingest_member call


def failure_backoff_seconds(consecutive_failures: int) -> int:
    return int(min(24 * 3600, 15 * 60 * (2 ** max(0, consecutive_failures - 1))))


def get_member(db: Session, cik: str) -> UniverseMember | None:
    return db.scalar(select(UniverseMember).where(UniverseMember.cik == normalize_cik(cik)))


def ensure_member(
    db: Session, cik: str, source: str, priority: int | None = None, now: datetime | None = None
) -> UniverseMember:
    cik = normalize_cik(cik)
    member = get_member(db, cik)
    if member is None:
        if priority is None:
            priority = int(db.scalar(select(func.count(UniverseMember.id))) or 0)
        member = UniverseMember(
            cik=cik, source=source, priority=priority, is_active=True, added_at=now or utcnow()
        )
        db.add(member)
        db.flush()
    return member


def seed_from_ciks(
    db: Session, ciks: Iterable[str], source: str, now: datetime | None = None
) -> dict:
    added = existing = skipped = 0
    base_priority = int(db.scalar(select(func.count(UniverseMember.id))) or 0)
    seen: set[str] = set()
    for raw in ciks:
        try:
            cik = normalize_cik(raw)
        except ValueError:
            skipped += 1
            continue
        if cik in seen:
            continue
        seen.add(cik)
        if get_member(db, cik) is not None:
            existing += 1
            continue
        ensure_member(db, cik, source, priority=base_priority + added, now=now)
        added += 1
    db.flush()
    return {"added": added, "existing": existing, "skipped": skipped}


def seed_from_lines(db: Session, lines: Iterable[str], source: str = "file") -> dict:
    cleaned = []
    for line in lines:
        text = line.split("#", 1)[0].strip()
        if text:
            cleaned.append(text)
    return seed_from_ciks(db, cleaned, source)


def seed_from_tickers(db: Session, payload: dict, top_n: int | None = None) -> dict:
    """Seed from the SEC ticker file in file order (dedup by CIK), optionally only the first N."""
    ciks: list[str] = []
    seen: set[str] = set()
    for row in parse_ticker_exchange(payload):
        if row["cik"] in seen:
            continue
        seen.add(row["cik"])
        ciks.append(row["cik"])
        if top_n is not None and len(ciks) >= top_n:
            break
    return seed_from_ciks(db, ciks, source="tickers")


def due_members(db: Session, limit: int, now: datetime | None = None) -> list[UniverseMember]:
    now = now or utcnow()
    stmt = (
        select(UniverseMember)
        .where(
            UniverseMember.is_active.is_(True),
            (UniverseMember.next_attempt_at.is_(None)) | (UniverseMember.next_attempt_at <= now),
        )
        .order_by(
            UniverseMember.priority,
            UniverseMember.next_attempt_at.asc().nulls_first(),
            UniverseMember.cik,
        )
        .limit(limit)
    )
    return list(db.scalars(stmt))


def count_due(db: Session, now: datetime | None = None) -> int:
    now = now or utcnow()
    return int(
        db.scalar(
            select(func.count(UniverseMember.id)).where(
                UniverseMember.is_active.is_(True),
                (UniverseMember.next_attempt_at.is_(None))
                | (UniverseMember.next_attempt_at <= now),
            )
        )
        or 0
    )


def record_success(member: UniverseMember, settings: Settings, now: datetime) -> None:
    member.last_attempt_at = now
    member.last_success_at = now
    member.consecutive_failures = 0
    member.last_error = None
    member.next_attempt_at = now + timedelta(seconds=settings.universe_refresh_interval_seconds)


def record_failure(member: UniverseMember, settings: Settings, now: datetime, error: str) -> None:
    member.last_attempt_at = now
    member.consecutive_failures += 1
    member.last_error = error[:300]
    if member.consecutive_failures >= settings.universe_max_consecutive_failures:
        member.is_active = False
        member.disabled_reason = (
            f"disabled after {member.consecutive_failures} consecutive failures: {error[:120]}"
        )
        member.next_attempt_at = None
    else:
        member.next_attempt_at = now + timedelta(
            seconds=failure_backoff_seconds(member.consecutive_failures)
        )


def ingest_member(
    db: Session,
    settings: Settings,
    client: SecClient,
    member: UniverseMember,
    run: IngestionRun,
    now: datetime,
    history_pages: int | None = None,
) -> tuple[bool, str | None]:
    """Ingest one universe member, recording success/failure on the member. Commits."""
    global last_result
    last_result = None
    try:
        last_result = ingest_company(
            db, client, member.cik, run=run, now=now, history_pages=history_pages
        )
        member = db.merge(member)
        record_success(member, settings, now)
        db.commit()
        return True, None
    except SecClientError as exc:
        db.rollback()
        error = f"{type(exc).__name__}: {exc}"
    except Exception as exc:  # noqa: BLE001 - keep the run alive
        db.rollback()
        error = type(exc).__name__
        logger.exception("universe ingest crashed", extra={"extra_fields": {"cik": member.cik}})
    member = db.merge(member)
    record_failure(member, settings, now, error)
    db.commit()
    return False, error.split(":")[0]


def bulk_ingest(
    db: Session,
    settings: Settings,
    client: SecClient,
    request_budget: int | None = None,
    max_companies: int | None = None,
    now: datetime | None = None,
    run: IngestionRun | None = None,
    history_pages: int | None = None,
) -> dict:
    """Ingest due universe members in priority order until the request budget is spent."""
    fixed_now = now
    now = now or utcnow()
    budget = settings.universe_request_budget_per_run if request_budget is None else request_budget
    pages = settings.sec_filings_history_pages if history_pages is None else history_pages
    cost = REQUESTS_PER_COMPANY + max(0, pages)  # estimate used to decide whether to start
    own_run = run is None
    if run is None:
        run = start_run(db, source="sec:universe")
        db.commit()
    summary: dict = {"ingested": 0, "failed": 0, "requests_used": 0, "remaining_due": 0}
    errors: list[str] = []
    summary["errors"] = errors
    while summary["requests_used"] + cost <= budget:
        if max_companies is not None and summary["ingested"] + summary["failed"] >= max_companies:
            break
        candidates = due_members(db, limit=1, now=now)
        if not candidates:
            break
        member = candidates[0]
        company_now = fixed_now or utcnow()
        before = client.metrics.snapshot()
        ok, error = ingest_member(db, settings, client, member, run, company_now, pages)
        # Charge the SEC requests actually made (retries and page fetches included).
        summary["requests_used"] += max(cost, client.metrics.delta(before)["requests"])
        if ok:
            summary["ingested"] += 1
        else:
            summary["failed"] += 1
            errors.append(f"{member.cik}: {error}")
        run = db.merge(run)
    summary["remaining_due"] = count_due(db, now)
    if own_run:
        run = db.merge(run)
        if not errors:
            status = "succeeded"
        else:
            status = "failed" if summary["ingested"] == 0 else "partial"
        finish_run(db, run, status, "; ".join(errors)[:2000] or None)
        take_snapshot(db, settings, run_id=run.id, now=now)
        db.commit()
    log_event(logger, logging.INFO, "universe bulk ingest", **summary)
    return summary
