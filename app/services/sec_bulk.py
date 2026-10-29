"""Ingest every SEC filer from the nightly bulk archives instead of per-company API calls.

The SEC recompiles two archives nightly (EDGAR API documentation, "Bulk data"):
- submissions.zip: one CIK##########.json per filer (same body as the Submissions API) plus
  CIK##########-submissions-NNN.json history pages.
- companyfacts.zip: one CIK##########.json per XBRL filer (same body as the Company Facts API).

Downloading both costs two requests per day under the fair-access policy (a declared
User-Agent with a contact address is still required). Ingestion reuses the per-company
pipeline unchanged through an archive-backed client, so normalization, idempotency, quality
statuses, provenance URLs and notification rules are identical to the API path.
"""

from __future__ import annotations

import hashlib
import json
import logging
import zipfile
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.logging import log_event
from app.db.models import Company, UniverseMember, utcnow
from app.services.ingestion import finish_run, ingest_company, start_run
from app.services.sec_client import (
    SecClient,
    SecClientError,
    SecMetrics,
    SecNotFound,
    SecResponse,
    company_facts_url,
    normalize_cik,
    submissions_url,
)

logger = logging.getLogger("app.sec_bulk")

BULK_SUBMISSIONS_URL = "https://www.sec.gov/Archives/edgar/daily-index/bulkdata/submissions.zip"
BULK_COMPANYFACTS_URL = "https://www.sec.gov/Archives/edgar/daily-index/xbrl/companyfacts.zip"
SCOPES = ("known", "facts", "universe", "ciks")


class ArchiveClient:
    """Duck-types SecClient for ingest_company, reading bodies from the bulk archives."""

    def __init__(
        self,
        settings: Settings,
        submissions_zip: Path,
        facts_zip: Path | None,
        archive_time: datetime | None = None,
    ) -> None:
        self.settings = settings
        self.metrics = SecMetrics()
        self._subs = zipfile.ZipFile(submissions_zip)
        self._facts = zipfile.ZipFile(facts_zip) if facts_zip else None
        self._subs_names = set(self._subs.namelist())
        self._facts_names = set(self._facts.namelist()) if self._facts else set()
        self.archive_time = archive_time or datetime.now(UTC)

    def close(self) -> None:
        self._subs.close()
        if self._facts:
            self._facts.close()

    def _read(self, zf: zipfile.ZipFile | None, names: set[str], member: str, url: str):
        if zf is None or member not in names:
            self.metrics.errors += 1
            raise SecNotFound("Not present in the SEC bulk archive", status_code=404, url=url)
        body = zf.read(member)
        self.metrics.requests += 1
        self.metrics.cached += 1
        try:
            data = json.loads(body)
        except ValueError as exc:
            raise SecClientError("Bulk archive member is not valid JSON", url=url) from exc
        return SecResponse(
            url=url,
            status_code=200,
            data=data,
            fetched_at=self.archive_time,
            from_cache=True,
            etag=None,
            last_modified=self.archive_time,
            payload_hash=hashlib.sha256(body).hexdigest(),
            retries=0,
        )

    def fetch_submissions(self, cik: str) -> SecResponse:
        cik = normalize_cik(cik)
        return self._read(self._subs, self._subs_names, f"CIK{cik}.json", submissions_url(cik))

    def fetch_company_facts(self, cik: str) -> SecResponse:
        cik = normalize_cik(cik)
        return self._read(self._facts, self._facts_names, f"CIK{cik}.json", company_facts_url(cik))

    def get_json(self, url: str) -> SecResponse:
        # Only used for submissions history pages, which the archive also contains.
        name = url.rsplit("/", 1)[-1]
        return self._read(self._subs, self._subs_names, name, url)

    # -- discovery -----------------------------------------------------------------------
    def ciks_with_facts(self) -> list[str]:
        return sorted(_cik_from_member(n) for n in self._facts_names if _cik_from_member(n))

    def ciks_with_submissions(self) -> list[str]:
        return sorted(_cik_from_member(n) for n in self._subs_names if _cik_from_member(n))


def _cik_from_member(name: str) -> str | None:
    base = name.rsplit("/", 1)[-1]
    if base.startswith("CIK") and base.endswith(".json") and "-" not in base:
        digits = base[3:-5]
        if digits.isdigit() and len(digits) == 10:
            return digits
    return None


def select_ciks(
    db: Session,
    client: ArchiveClient,
    scope: str,
    ciks: Iterable[str] | None = None,
    limit: int | None = None,
) -> list[str]:
    """known = companies already in the database (seed with scripts/import_tickers.py);
    facts = every XBRL filer in companyfacts.zip (about all operating public companies);
    universe = active universe members; ciks = an explicit list."""
    if scope == "known":
        wanted = list(db.scalars(select(Company.cik).order_by(Company.cik)))
    elif scope == "facts":
        wanted = client.ciks_with_facts()
    elif scope == "universe":
        wanted = list(
            db.scalars(
                select(UniverseMember.cik)
                .where(UniverseMember.is_active.is_(True))
                .order_by(UniverseMember.priority)
            )
        )
    elif scope == "ciks":
        wanted = [normalize_cik(c) for c in (ciks or [])]
    else:
        raise ValueError(f"scope must be one of {SCOPES}")
    present = set(client.ciks_with_submissions())
    selected = [c for c in wanted if c in present]
    return selected[:limit] if limit else selected


def bulk_ingest(
    db: Session,
    settings: Settings,
    submissions_zip: Path,
    facts_zip: Path | None,
    scope: str = "known",
    ciks: Iterable[str] | None = None,
    limit: int | None = None,
    archive_time: datetime | None = None,
    include_facts: bool = True,
    progress_every: int = 500,
) -> dict:
    """Ingest the selected CIKs from local archives. Commits per company; records one run."""
    client = ArchiveClient(settings, submissions_zip, facts_zip, archive_time)
    run = start_run(db, source="sec:bulk")
    db.commit()
    summary = {
        "scope": scope,
        "selected": 0,
        "ingested": 0,
        "failed": 0,
        "filings_inserted": 0,
        "facts_inserted": 0,
        "facts_unavailable": 0,
        "errors": [],
    }
    try:
        selected = select_ciks(db, client, scope, ciks, limit)
        summary["selected"] = len(selected)
        for i, cik in enumerate(selected, 1):
            now = utcnow()
            try:
                result = ingest_company(
                    db, client, cik, run=run, now=now, include_facts=include_facts
                )
            except SecClientError as exc:
                db.rollback()
                summary["failed"] += 1
                if len(summary["errors"]) < 50:
                    summary["errors"].append(f"{cik}: {type(exc).__name__}")
                run = db.merge(run)
                continue
            run = db.merge(run)
            summary["ingested"] += 1
            summary["filings_inserted"] += result.filings_inserted
            summary["facts_inserted"] += result.facts_inserted
            if not result.facts_available:
                summary["facts_unavailable"] += 1
            member = db.scalar(select(UniverseMember).where(UniverseMember.cik == cik))
            if member is not None:
                member.last_attempt_at = now
                member.last_success_at = now
                member.consecutive_failures = 0
                db.commit()
            if progress_every and i % progress_every == 0:
                log_event(logger, logging.INFO, "sec bulk progress", done=i, of=len(selected))
    finally:
        client.close()
    run = db.merge(run)
    if summary["failed"] == 0:
        status = "succeeded"
    else:
        status = "failed" if summary["ingested"] == 0 else "partial"
    finish_run(db, run, status, "; ".join(summary["errors"])[:2000] or None)
    db.commit()
    from app.services.quality import take_snapshot

    take_snapshot(db, settings, run_id=run.id)
    db.commit()
    log_event(
        logger,
        logging.INFO,
        "sec bulk ingest",
        **{k: v for k, v in summary.items() if k != "errors"},
    )
    return summary


def download_archives(settings: Settings, client: SecClient | None = None) -> dict:
    """Download (or revalidate) both archives into SEC_BULK_DIR. Two SEC requests."""
    own = client is None
    client = client or SecClient(settings)
    base = Path(settings.sec_bulk_dir)
    try:
        subs = client.download_file(BULK_SUBMISSIONS_URL, base / "submissions.zip")
        facts = client.download_file(BULK_COMPANYFACTS_URL, base / "companyfacts.zip")
    finally:
        if own:
            client.close()
    return {"submissions": subs, "companyfacts": facts}
