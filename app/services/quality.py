"""Data-quality snapshots and the operator report (AGENTS.md section 12 metrics)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.timeutil import iso_z
from app.db.models import (
    Company,
    CompanyWatch,
    DataQualitySnapshot,
    Filing,
    FinancialFact,
    ListedInstrument,
    ListingEvent,
    NotificationDelivery,
    UniverseMember,
)


def _count(db: Session, stmt) -> int:
    return int(db.scalar(stmt) or 0)


def take_snapshot(
    db: Session, settings: Settings, run_id: uuid.UUID | None = None, now: datetime | None = None
) -> DataQualitySnapshot:
    now = now or datetime.now(UTC)
    stale_cutoff = now - timedelta(seconds=settings.freshness_stale_after_seconds)
    day_ago = now - timedelta(hours=24)

    facts_total = _count(db, select(func.count(FinancialFact.id)))
    by_quality = {
        status: int(n)
        for status, n in db.execute(
            select(FinancialFact.quality_status, func.count(FinancialFact.id)).group_by(
                FinancialFact.quality_status
            )
        ).all()
    }
    with_provenance = _count(
        db,
        select(func.count(FinancialFact.id)).where(
            FinancialFact.source_url != "",
            FinancialFact.source_tag != "",
            FinancialFact.unit != "",
            FinancialFact.mapping_version != "",
        ),
    )
    dup_subq = (
        select(Filing.cik, Filing.accession_number)
        .group_by(Filing.cik, Filing.accession_number)
        .having(func.count(Filing.id) > 1)
        .subquery()
    )
    oldest_pending = db.scalar(
        select(func.min(NotificationDelivery.created_at)).where(
            NotificationDelivery.status.in_(["pending", "retrying"])
        )
    )
    snap = DataQualitySnapshot(
        run_id=run_id,
        taken_at=now,
        companies_known=_count(db, select(func.count(Company.id))),
        companies_ingested=_count(
            db, select(func.count(Company.id)).where(Company.last_processed_at.is_not(None))
        ),
        companies_stale=_count(
            db,
            select(func.count(Company.id)).where(
                Company.last_successful_fetch_at.is_not(None),
                Company.last_successful_fetch_at < stale_cutoff,
            ),
        ),
        filings_total=_count(db, select(func.count(Filing.id))),
        filings_with_accepted=_count(
            db, select(func.count(Filing.id)).where(Filing.accepted_at.is_not(None))
        ),
        duplicate_filings=_count(db, select(func.count()).select_from(dup_subq)),
        facts_total=facts_total,
        facts_ok=by_quality.get("ok", 0),
        facts_partial=by_quality.get("partial", 0),
        facts_ambiguous=by_quality.get("ambiguous_mapping", 0),
        facts_invalid=by_quality.get("invalid_source_value", 0),
        facts_with_provenance_pct=round(100.0 * with_provenance / facts_total, 3)
        if facts_total
        else None,
        pending_deliveries=_count(
            db,
            select(func.count(NotificationDelivery.id)).where(
                NotificationDelivery.status.in_(["pending", "retrying"])
            ),
        ),
        delivered_24h=_count(
            db,
            select(func.count(NotificationDelivery.id)).where(
                and_(
                    NotificationDelivery.status == "delivered",
                    NotificationDelivery.delivered_at >= day_ago,
                )
            ),
        ),
        failed_24h=_count(
            db,
            select(func.count(NotificationDelivery.id)).where(
                NotificationDelivery.status == "failed", NotificationDelivery.created_at >= day_ago
            ),
        ),
        oldest_pending_age_seconds=int((now - oldest_pending).total_seconds())
        if oldest_pending
        else None,
        active_watches=_count(
            db, select(func.count(CompanyWatch.id)).where(CompanyWatch.is_active.is_(True))
        ),
        universe_active=_count(
            db, select(func.count(UniverseMember.id)).where(UniverseMember.is_active.is_(True))
        ),
        universe_due=_count(
            db,
            select(func.count(UniverseMember.id)).where(
                UniverseMember.is_active.is_(True),
                (UniverseMember.next_attempt_at.is_(None))
                | (UniverseMember.next_attempt_at <= now),
            ),
        ),
        universe_disabled=_count(
            db, select(func.count(UniverseMember.id)).where(UniverseMember.is_active.is_(False))
        ),
        listings_total=_count(db, select(func.count(ListedInstrument.id))),
        listings_listed=_count(
            db,
            select(func.count(ListedInstrument.id)).where(ListedInstrument.status == "listed"),
        ),
        listing_events_24h=_count(
            db, select(func.count(ListingEvent.id)).where(ListingEvent.detected_at >= day_ago)
        ),
    )
    db.add(snap)
    db.flush()
    return snap


def latest_snapshot(db: Session) -> DataQualitySnapshot | None:
    return db.scalar(
        select(DataQualitySnapshot).order_by(DataQualitySnapshot.taken_at.desc()).limit(1)
    )


def snapshot_to_dict(snap: DataQualitySnapshot) -> dict:
    return {
        "taken_at": iso_z(snap.taken_at),
        "run_id": str(snap.run_id) if snap.run_id else None,
        "companies": {
            "known": snap.companies_known,
            "ingested": snap.companies_ingested,
            "stale": snap.companies_stale,
        },
        "filings": {
            "total": snap.filings_total,
            "with_acceptance_timestamp": snap.filings_with_accepted,
            "duplicates": snap.duplicate_filings,
        },
        "facts": {
            "total": snap.facts_total,
            "by_quality": {
                "ok": snap.facts_ok,
                "partial": snap.facts_partial,
                "ambiguous_mapping": snap.facts_ambiguous,
                "invalid_source_value": snap.facts_invalid,
            },
            "with_provenance_pct": snap.facts_with_provenance_pct,
        },
        "notifications": {
            "pending": snap.pending_deliveries,
            "delivered_24h": snap.delivered_24h,
            "failed_24h": snap.failed_24h,
            "oldest_pending_age_seconds": snap.oldest_pending_age_seconds,
            "active_watches": snap.active_watches,
        },
        "universe": {
            "active": snap.universe_active,
            "due": snap.universe_due,
            "disabled": snap.universe_disabled,
        },
        "listings": {
            "total": snap.listings_total,
            "listed": snap.listings_listed,
            "events_24h": snap.listing_events_24h,
        },
    }


def render_report(db: Session, limit: int = 10) -> str:
    snaps = list(
        db.scalars(
            select(DataQualitySnapshot).order_by(DataQualitySnapshot.taken_at.desc()).limit(limit)
        )
    )
    if not snaps:
        return "No quality snapshots yet. Run the poller or bulk ingestion first."
    latest = snaps[0]
    lines = [
        f"Latest snapshot {latest.taken_at.isoformat()}",
        f"  companies: known={latest.companies_known} ingested={latest.companies_ingested} "
        f"stale={latest.companies_stale}",
        f"  filings: total={latest.filings_total} with_accepted={latest.filings_with_accepted} "
        f"duplicates={latest.duplicate_filings}",
        f"  facts: total={latest.facts_total} ok={latest.facts_ok} partial={latest.facts_partial} "
        f"ambiguous={latest.facts_ambiguous} invalid={latest.facts_invalid} "
        f"provenance={latest.facts_with_provenance_pct}%",
        f"  notifications: pending={latest.pending_deliveries} "
        f"delivered_24h={latest.delivered_24h} failed_24h={latest.failed_24h} "
        f"oldest_pending_s={latest.oldest_pending_age_seconds}",
        f"  universe: active={latest.universe_active} due={latest.universe_due} "
        f"disabled={latest.universe_disabled}",
        "",
        "Trend (newest first): taken_at | companies_ingested | filings | facts | ambiguous "
        "| pending",
    ]
    for s in snaps:
        lines.append(
            f"  {s.taken_at.strftime('%Y-%m-%d %H:%M')} | {s.companies_ingested} | "
            f"{s.filings_total} | {s.facts_total} | {s.facts_ambiguous} | {s.pending_deliveries}"
        )
    return "\n".join(lines)
