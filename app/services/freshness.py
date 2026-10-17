"""Freshness summary for a company. Only compares timestamps that are actually comparable."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db.models import Company, Filing, IngestionRun


def company_freshness(db: Session, company: Company, settings: Settings, now=None) -> dict:
    now = now or datetime.now(UTC)
    notes: list[str] = []

    latest = db.scalar(
        select(Filing)
        .where(Filing.cik == company.cik)
        .order_by(Filing.filing_date.desc().nulls_last(), Filing.accession_number.desc())
        .limit(1)
    )
    latest_detected = db.scalar(
        select(Filing)
        .where(Filing.cik == company.cik)
        .order_by(Filing.first_detected_at.desc(), Filing.accession_number.desc())
        .limit(1)
    )

    latest_filing = None
    if latest is not None:
        processing_seconds = None
        if latest.processed_at and latest.first_detected_at:
            processing_seconds = round(
                (latest.processed_at - latest.first_detected_at).total_seconds(), 3
            )
        acceptance_to_detection = None
        if latest.accepted_at is not None:
            acceptance_to_detection = round(
                (latest.first_detected_at - latest.accepted_at).total_seconds(), 3
            )
        else:
            notes.append(
                "The SEC source did not provide a precise acceptance timestamp for the latest "
                "filing; acceptance_to_detection_seconds is null."
            )
        source_date_age = None
        if latest.filing_date is not None:
            midnight = datetime.combine(latest.filing_date, datetime.min.time(), tzinfo=UTC)
            source_date_age = int((now - midnight).total_seconds())
        latest_filing = {
            "accession_number": latest.accession_number,
            "form_type": latest.form_type,
            "filing_date": latest.filing_date,
            "accepted_at": latest.accepted_at,
            "source_published_at": latest.source_published_at,
            "first_detected_at": latest.first_detected_at,
            "processed_at": latest.processed_at,
            "publication_to_detection_seconds": None,
            "acceptance_to_detection_seconds": acceptance_to_detection,
            "source_date_age_seconds": source_date_age,
            "processing_seconds": processing_seconds,
            "quality_status": latest.quality_status,
        }
        notes.append(
            "publication_to_detection_seconds is always null: the SEC submissions feed exposes an "
            "acceptance timestamp, not a public-dissemination timestamp."
        )
        notes.append(
            "source_date_age_seconds is measured from the date-only filing_date at 00:00 UTC and "
            "is not a latency figure."
        )
    else:
        notes.append("No filings have been ingested for this company yet.")

    last_run = db.scalar(select(IngestionRun).order_by(IngestionRun.started_at.desc()).limit(1))

    last_fetch = company.last_successful_fetch_at
    age_seconds = int((now - last_fetch).total_seconds()) if last_fetch else None
    if last_fetch is None:
        status = "unavailable"
        notes.append("This company has not been fetched from the SEC yet.")
    elif age_seconds is not None and age_seconds > settings.freshness_stale_after_seconds:
        status = "stale"
        notes.append(
            f"Last successful SEC fetch is older than {settings.freshness_stale_after_seconds}s."
        )
    elif latest is None or latest.quality_status != "ok" or company.quality_status != "ok":
        status = "partial"
    else:
        status = "ok"

    if company.last_fetch_error:
        notes.append("The most recent fetch attempt failed; data shown is from the last success.")

    return {
        "cik": company.cik,
        "last_successful_fetch_at": last_fetch,
        "last_successful_fetch_age_seconds": age_seconds,
        "source_updated_at": company.source_updated_at,
        "last_fetch_error_at": company.last_fetch_error_at,
        "last_fetch_error": company.last_fetch_error,
        "latest_filing": latest_filing,
        "latest_detected_filing_at": latest_detected.first_detected_at if latest_detected else None,
        "ingestion": {
            "last_run_started_at": last_run.started_at if last_run else None,
            "last_run_finished_at": last_run.finished_at if last_run else None,
            "last_run_status": last_run.status if last_run else None,
            "last_run_error_count": last_run.error_count if last_run else None,
            "poll_interval_seconds": settings.ingestion_poll_interval_seconds,
            "stale_after_seconds": settings.freshness_stale_after_seconds,
        },
        "status": status,
        "notes": notes,
    }


def stale_threshold(settings: Settings) -> timedelta:
    return timedelta(seconds=settings.freshness_stale_after_seconds)
