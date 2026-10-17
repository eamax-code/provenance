"""Ingestion: SEC payloads -> companies, filings, facts, runs, notification events.

Idempotent: re-running on the same payload inserts nothing new, preserves
first_detected_at, and updates processed_at / changed metadata only.
"""

from __future__ import annotations

import hashlib
import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.logging import log_event
from app.db.models import Company, FinancialFact, IngestionRun, utcnow
from app.db.models import Filing as FilingRow
from app.services import notifications
from app.services.fact_normalizer import NormalizedFact, normalize_company_facts
from app.services.sec_client import (
    SecClient,
    SecClientError,
    SecNotFound,
    SecUnavailable,
    filing_index_url,
    normalize_cik,
    submissions_url,
    ticker_exchange_url,
)

logger = logging.getLogger("app.ingestion")


class IngestionError(Exception):
    pass


@dataclass
class CompanyRecord:
    cik: str
    legal_name: str
    ticker: str | None
    exchange: str | None
    sic_code: str | None
    sic_description: str | None
    entity_type: str | None
    state_of_incorporation: str | None
    fiscal_year_end: str | None
    source_url: str


@dataclass
class FilingRecord:
    cik: str
    accession_number: str
    form_type: str
    filing_date: date | None
    report_date: date | None
    accepted_at: datetime | None
    primary_document: str | None
    source_url: str
    quality_status: str
    notes: list[str] = field(default_factory=list)

    def payload_hash(self) -> str:
        return hashlib.sha256(
            json.dumps(
                {
                    "accn": self.accession_number,
                    "form": self.form_type,
                    "filing_date": self.filing_date.isoformat() if self.filing_date else None,
                    "report_date": self.report_date.isoformat() if self.report_date else None,
                    "accepted_at": self.accepted_at.isoformat() if self.accepted_at else None,
                    "primary_document": self.primary_document,
                },
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()


@dataclass
class IngestResult:
    cik: str
    run_id: uuid.UUID
    filings_seen: int = 0
    filings_inserted: int = 0
    filings_updated: int = 0
    facts_seen: int = 0
    facts_inserted: int = 0
    facts_updated: int = 0
    new_filing_ids: list[uuid.UUID] = field(default_factory=list)
    notifications_created: int = 0
    errors: list[str] = field(default_factory=list)
    facts_available: bool = True


# --- parsing --------------------------------------------------------------------------------


def parse_iso_date(value: Any) -> date | None:
    if not value or not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def parse_timestamp(value: Any) -> datetime | None:
    """Parse an SEC acceptanceDateTime. Returns None unless it is a full timestamp."""
    if not value or not isinstance(value, str):
        return None
    text = value.strip()
    if len(text) < 16:  # date-only strings are not precise timestamps
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)  # SEC publishes acceptance times in UTC with a Z suffix
    return dt.astimezone(UTC)


def _str_or_none(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def parse_submissions(
    payload: dict, www_base: str = "https://www.sec.gov"
) -> tuple[CompanyRecord, list[FilingRecord]]:
    if not isinstance(payload, dict) or "cik" not in payload:
        raise IngestionError("submissions payload missing 'cik'")
    try:
        cik = normalize_cik(payload["cik"])
    except ValueError as exc:
        raise IngestionError("submissions payload has an invalid cik") from exc
    name = _str_or_none(payload.get("name"))
    if not name:
        raise IngestionError("submissions payload missing 'name'")

    tickers = payload.get("tickers") if isinstance(payload.get("tickers"), list) else []
    exchanges = payload.get("exchanges") if isinstance(payload.get("exchanges"), list) else []
    company = CompanyRecord(
        cik=cik,
        legal_name=name,
        ticker=_str_or_none(tickers[0]) if tickers else None,
        exchange=_str_or_none(exchanges[0]) if exchanges else None,
        sic_code=_str_or_none(payload.get("sic")),
        sic_description=_str_or_none(payload.get("sicDescription")),
        entity_type=_str_or_none(payload.get("entityType")),
        state_of_incorporation=_str_or_none(payload.get("stateOfIncorporation")),
        fiscal_year_end=_str_or_none(payload.get("fiscalYearEnd")),
        source_url=submissions_url(cik),
    )

    filings: list[FilingRecord] = []
    recent = (
        (payload.get("filings") or {}).get("recent")
        if isinstance(payload.get("filings"), dict)
        else None
    )
    if not isinstance(recent, dict):
        return company, filings

    accessions = recent.get("accessionNumber") or []
    if not isinstance(accessions, list):
        return company, filings
    n = len(accessions)

    def col(name: str) -> list:
        values = recent.get(name)
        if isinstance(values, list) and len(values) == n:
            return values
        return [None] * n

    forms = col("form")
    filing_dates = col("filingDate")
    report_dates = col("reportDate")
    accepted = col("acceptanceDateTime")
    primary_docs = col("primaryDocument")

    seen: set[str] = set()
    for i in range(n):
        accn = _str_or_none(accessions[i])
        if not accn or accn in seen or not _valid_accession(accn):
            continue
        seen.add(accn)
        form = _str_or_none(forms[i])
        notes: list[str] = []
        if not form:
            form = "UNKNOWN"
            notes.append("form type missing in source")
        fdate = parse_iso_date(filing_dates[i])
        if fdate is None:
            notes.append("filing date missing or unparseable in source")
        accepted_at = parse_timestamp(accepted[i])
        if accepted_at is None:
            notes.append("precise acceptance timestamp not provided by source")
        quality = "ok" if not notes else "partial"
        filings.append(
            FilingRecord(
                cik=cik,
                accession_number=accn,
                form_type=form,
                filing_date=fdate,
                report_date=parse_iso_date(report_dates[i]),
                accepted_at=accepted_at,
                primary_document=_str_or_none(primary_docs[i]),
                source_url=filing_index_url(cik, accn, www_base),
                quality_status=quality,
                notes=notes,
            )
        )
    return company, filings


def _valid_accession(accn: str) -> bool:
    parts = accn.split("-")
    return (
        len(parts) == 3
        and len(parts[0]) == 10
        and len(parts[1]) == 2
        and len(parts[2]) == 6
        and all(p.isdigit() for p in parts)
    )


def parse_ticker_exchange(payload: dict) -> list[dict]:
    """Parse company_tickers_exchange.json -> list of {cik, name, ticker, exchange}."""
    if not isinstance(payload, dict):
        return []
    fields = payload.get("fields")
    data = payload.get("data")
    if not isinstance(fields, list) or not isinstance(data, list):
        return []
    idx = {name: i for i, name in enumerate(fields)}
    required = {"cik", "name", "ticker"}
    if not required.issubset(idx):
        return []
    out = []
    for row in data:
        if not isinstance(row, list) or len(row) < len(fields):
            continue
        try:
            cik = normalize_cik(row[idx["cik"]])
        except (ValueError, TypeError):
            continue
        name = _str_or_none(row[idx["name"]])
        if not name:
            continue
        out.append(
            {
                "cik": cik,
                "name": name,
                "ticker": _str_or_none(row[idx["ticker"]]),
                "exchange": _str_or_none(row[idx["exchange"]]) if "exchange" in idx else None,
            }
        )
    return out


# --- persistence ----------------------------------------------------------------------------


def start_run(db: Session, source: str) -> IngestionRun:
    run = IngestionRun(source=source, started_at=utcnow(), status="running")
    db.add(run)
    db.flush()
    return run


def finish_run(db: Session, run: IngestionRun, status: str, error_summary: str | None = None):
    run.finished_at = utcnow()
    run.status = status
    run.error_summary = error_summary[:2000] if error_summary else None
    db.flush()


def import_ticker_mapping(db: Session, payload: dict, now: datetime | None = None) -> dict:
    """Seed/refresh companies from the SEC ticker/exchange file (no filings/facts)."""
    now = now or utcnow()
    rows = parse_ticker_exchange(payload)
    inserted = updated = 0
    # Prefer the first ticker listed for a CIK; the file lists multiple classes per issuer.
    by_cik: dict[str, dict] = {}
    for r in rows:
        by_cik.setdefault(r["cik"], r)
    existing = (
        {c.cik: c for c in db.scalars(select(Company).where(Company.cik.in_(list(by_cik))))}
        if by_cik
        else {}
    )
    for cik, r in by_cik.items():
        c = existing.get(cik)
        if c is None:
            db.add(
                Company(
                    cik=cik,
                    legal_name=r["name"],
                    ticker=r["ticker"],
                    exchange=r["exchange"],
                    source_url=ticker_exchange_url(),
                    first_detected_at=now,
                    quality_status="partial",
                    created_at=now,
                    updated_at=now,
                )
            )
            inserted += 1
        else:
            changed = False
            if c.ticker != r["ticker"] and r["ticker"]:
                c.ticker = r["ticker"]
                changed = True
            if c.exchange != r["exchange"] and r["exchange"]:
                c.exchange = r["exchange"]
                changed = True
            if changed:
                c.updated_at = now
                updated += 1
    db.flush()
    return {"rows": len(rows), "companies": len(by_cik), "inserted": inserted, "updated": updated}


def upsert_company(db: Session, rec: CompanyRecord, now: datetime, source_updated_at=None):
    company = db.scalar(select(Company).where(Company.cik == rec.cik))
    if company is None:
        company = Company(
            cik=rec.cik,
            legal_name=rec.legal_name,
            first_detected_at=now,
            source_url=rec.source_url,
            created_at=now,
            updated_at=now,
            quality_status="partial",
        )
        db.add(company)
    company.legal_name = rec.legal_name
    if rec.ticker:
        company.ticker = rec.ticker
    if rec.exchange:
        company.exchange = rec.exchange
    company.sic_code = rec.sic_code
    company.sic_description = rec.sic_description
    company.entity_type = rec.entity_type
    company.state_of_incorporation = rec.state_of_incorporation
    company.fiscal_year_end = rec.fiscal_year_end
    company.source_url = rec.source_url
    if source_updated_at is not None:
        company.source_updated_at = source_updated_at
    company.updated_at = now
    db.flush()
    return company


def upsert_filings(
    db: Session, records: list[FilingRecord], run_id: uuid.UUID, now: datetime
) -> tuple[int, int, list[FilingRow]]:
    """Insert new filings and refresh changed ones. Returns (inserted, updated, new_rows)."""
    if not records:
        return 0, 0, []
    cik = records[0].cik
    existing = {
        f.accession_number: f for f in db.scalars(select(FilingRow).where(FilingRow.cik == cik))
    }
    inserted = updated = 0
    new_rows: list[FilingRow] = []
    for rec in records:
        h = rec.payload_hash()
        row = existing.get(rec.accession_number)
        if row is None:
            row = FilingRow(
                cik=rec.cik,
                accession_number=rec.accession_number,
                form_type=rec.form_type,
                filing_date=rec.filing_date,
                report_date=rec.report_date,
                accepted_at=rec.accepted_at,
                source_published_at=None,
                primary_document=rec.primary_document,
                source_url=rec.source_url,
                source_payload_hash=h,
                first_detected_at=now,
                processed_at=now,
                ingestion_run_id=run_id,
                quality_status=rec.quality_status,
                created_at=now,
            )
            db.add(row)
            existing[rec.accession_number] = row
            new_rows.append(row)
            inserted += 1
        elif row.source_payload_hash != h:
            row.form_type = rec.form_type
            row.filing_date = rec.filing_date
            row.report_date = rec.report_date
            row.accepted_at = rec.accepted_at
            row.primary_document = rec.primary_document
            row.source_url = rec.source_url
            row.source_payload_hash = h
            row.processed_at = now
            row.ingestion_run_id = run_id
            row.quality_status = rec.quality_status
            updated += 1
    db.flush()
    return inserted, updated, new_rows


def upsert_facts(
    db: Session, cik: str, facts: list[NormalizedFact], now: datetime
) -> tuple[int, int]:
    """Insert new fact observations; never delete older ones. Returns (inserted, updated)."""
    if not facts:
        return 0, 0
    existing = {
        f.observation_key: f
        for f in db.scalars(select(FinancialFact).where(FinancialFact.cik == cik))
    }
    inserted = updated = 0
    seen_keys: set[str] = set()
    for nf in facts:
        key = nf.observation_key
        if key in seen_keys:
            continue  # exact duplicate observation within the payload
        seen_keys.add(key)
        h = nf.source_payload_hash()
        row = existing.get(key)
        if row is None:
            db.add(
                FinancialFact(
                    cik=cik,
                    metric=nf.metric,
                    value=nf.value,
                    unit=nf.unit,
                    currency=nf.currency,
                    period_start=nf.period_start,
                    period_end=nf.period_end,
                    period_type=nf.period_type,
                    period_class=nf.period_class,
                    fiscal_year=nf.fiscal_year,
                    fiscal_period=nf.fiscal_period,
                    form_type=nf.form_type,
                    filed_date=nf.filed_date,
                    accession_number=nf.accession_number,
                    source_tag=nf.source_tag,
                    source_taxonomy=nf.source_taxonomy,
                    source_url=nf.source_url,
                    mapping_version=nf.mapping_version,
                    quality_status=nf.quality_status,
                    derived=nf.derived,
                    derivation=json.dumps(nf.derivation) if nf.derivation else None,
                    observation_key=key,
                    source_payload_hash=h,
                    first_detected_at=now,
                    processed_at=now,
                    created_at=now,
                )
            )
            inserted += 1
        elif row.source_payload_hash != h or row.quality_status != nf.quality_status:
            row.value = nf.value
            row.fiscal_year = nf.fiscal_year
            row.fiscal_period = nf.fiscal_period
            row.form_type = nf.form_type
            row.filed_date = nf.filed_date
            row.quality_status = nf.quality_status
            row.period_class = nf.period_class
            row.source_payload_hash = h
            row.processed_at = now
            updated += 1
    db.flush()
    return inserted, updated


def _redact_error(exc: Exception) -> str:
    text = f"{type(exc).__name__}: {exc}"
    return text[:300]


def ingest_company(
    db: Session,
    client: SecClient,
    cik: str,
    run: IngestionRun | None = None,
    now: datetime | None = None,
    include_facts: bool = True,
) -> IngestResult:
    """Full vertical ingestion for one company. Commits on success; records failures."""
    cik = normalize_cik(cik)
    now = now or utcnow()
    own_run = run is None
    if run is None:
        run = start_run(db, source="sec:company")
    result = IngestResult(cik=cik, run_id=run.id)
    www_base = client.settings.sec_base_www_url

    try:
        sub = client.fetch_submissions(cik)
    except SecNotFound:
        _record_fetch_failure(db, cik, "submissions not found at SEC", now)
        run.error_count += 1
        if own_run:
            finish_run(db, run, "failed", "submissions not found")
        db.commit()
        raise
    except (SecUnavailable, SecClientError) as exc:
        _record_fetch_failure(db, cik, _redact_error(exc), now)
        run.error_count += 1
        if own_run:
            finish_run(db, run, "failed", _redact_error(exc))
        db.commit()
        raise

    try:
        company_rec, filing_recs = parse_submissions(sub.data, www_base)
    except IngestionError as exc:
        _record_fetch_failure(db, cik, _redact_error(exc), now)
        run.error_count += 1
        if own_run:
            finish_run(db, run, "failed", _redact_error(exc))
        db.commit()
        raise

    company = upsert_company(db, company_rec, now, source_updated_at=sub.last_modified)
    run.companies_seen += 1
    ins, upd, new_rows = upsert_filings(db, filing_recs, run.id, now)
    result.filings_seen = len(filing_recs)
    result.filings_inserted, result.filings_updated = ins, upd
    run.filings_seen += len(filing_recs)
    run.inserted_count += ins
    run.updated_count += upd

    # Notifications: one per active watch per newly detected filing (idempotent event ids).
    # Only filings dated on/after the company's first ingestion count as "new" events so a
    # backfill of a thousand historical filings does not fan out a thousand webhooks.
    first_ingestion = company.last_processed_at is None
    if not first_ingestion:
        for row in new_rows:
            created = notifications.create_deliveries_for_filing(db, row, now)
            result.notifications_created += created
    result.new_filing_ids = [r.id for r in new_rows]

    if include_facts:
        try:
            facts_resp = client.fetch_company_facts(cik)
            facts = normalize_company_facts(facts_resp.data, cik, www_base)
            fi, fu = upsert_facts(db, cik, facts, now)
            result.facts_seen = len(facts)
            result.facts_inserted, result.facts_updated = fi, fu
            run.facts_seen += len(facts)
            run.inserted_count += fi
            run.updated_count += fu
        except SecNotFound:
            result.facts_available = False
            result.errors.append("company facts not available at SEC for this CIK")
        except (SecUnavailable, SecClientError) as exc:
            result.facts_available = False
            result.errors.append(_redact_error(exc))
            run.error_count += 1

    company.last_successful_fetch_at = now
    company.last_processed_at = utcnow()
    company.last_fetch_error = None
    company.last_fetch_error_at = None
    company.quality_status = "ok" if result.facts_available and not result.errors else "partial"
    if own_run:
        finish_run(
            db,
            run,
            "succeeded" if not result.errors else "partial",
            "; ".join(result.errors) or None,
        )
    db.commit()
    log_event(
        logger,
        logging.INFO,
        "company ingested",
        cik=cik,
        filings_inserted=ins,
        filings_updated=upd,
        facts_inserted=result.facts_inserted,
        notifications=result.notifications_created,
    )
    return result


def _record_fetch_failure(db: Session, cik: str, message: str, now: datetime) -> None:
    company = db.scalar(select(Company).where(Company.cik == cik))
    if company is not None:
        company.last_fetch_error = message
        company.last_fetch_error_at = now
        company.updated_at = now
        db.flush()
