"""SQLAlchemy models. See docs/data-dictionary.md for field meaning."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    Date,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.db.types import BigSerial, UTCDateTime


def utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class Company(Base):
    __tablename__ = "companies"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    cik: Mapped[str] = mapped_column(String(10), nullable=False, unique=True, index=True)
    legal_name: Mapped[str] = mapped_column(Text, nullable=False)
    ticker: Mapped[str | None] = mapped_column(Text, nullable=True)
    exchange: Mapped[str | None] = mapped_column(Text, nullable=True)
    sic_code: Mapped[str | None] = mapped_column(Text, nullable=True)
    sic_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    entity_type: Mapped[str | None] = mapped_column(Text, nullable=True)
    state_of_incorporation: Mapped[str | None] = mapped_column(Text, nullable=True)
    fiscal_year_end: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    source_updated_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    first_detected_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    last_processed_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    last_successful_fetch_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    last_fetch_error_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    last_fetch_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    quality_status: Mapped[str] = mapped_column(Text, nullable=False, default="partial")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime, nullable=False, default=utcnow, onupdate=utcnow
    )


Index("ix_companies_ticker_lower", Company.ticker)
Index("ix_companies_legal_name", Company.legal_name)


class Filing(Base):
    __tablename__ = "filings"
    __table_args__ = (
        UniqueConstraint("cik", "accession_number", name="uq_filings_cik_accession"),
        Index("ix_filings_cik_filing_date", "cik", "filing_date"),
        Index("ix_filings_cik_first_detected", "cik", "first_detected_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    cik: Mapped[str] = mapped_column(String(10), ForeignKey("companies.cik"), nullable=False)
    accession_number: Mapped[str] = mapped_column(String(25), nullable=False)
    form_type: Mapped[str] = mapped_column(Text, nullable=False)
    filing_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    report_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    accepted_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    source_published_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    primary_document: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    source_payload_hash: Mapped[str | None] = mapped_column(Text, nullable=True)
    first_detected_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    processed_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    ingestion_run_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    quality_status: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)


class FinancialFact(Base):
    __tablename__ = "financial_facts"
    __table_args__ = (
        UniqueConstraint("observation_key", name="uq_financial_facts_observation_key"),
        Index("ix_facts_cik_metric_period_end", "cik", "metric", "period_end"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    cik: Mapped[str] = mapped_column(String(10), ForeignKey("companies.cik"), nullable=False)
    metric: Mapped[str] = mapped_column(Text, nullable=False)
    value: Mapped[Decimal | None] = mapped_column(Numeric(38, 6), nullable=True)
    unit: Mapped[str] = mapped_column(Text, nullable=False)
    currency: Mapped[str | None] = mapped_column(Text, nullable=True)
    period_start: Mapped[date | None] = mapped_column(Date, nullable=True)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)
    period_type: Mapped[str] = mapped_column(Text, nullable=False)  # instant | duration
    period_class: Mapped[str] = mapped_column(Text, nullable=False)  # annual|quarterly|ytd|other
    fiscal_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    fiscal_period: Mapped[str | None] = mapped_column(Text, nullable=True)
    form_type: Mapped[str | None] = mapped_column(Text, nullable=True)
    filed_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    accession_number: Mapped[str | None] = mapped_column(String(25), nullable=True)
    source_tag: Mapped[str] = mapped_column(Text, nullable=False)
    source_taxonomy: Mapped[str] = mapped_column(Text, nullable=False, default="us-gaap")
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    mapping_version: Mapped[str] = mapped_column(Text, nullable=False)
    quality_status: Mapped[str] = mapped_column(Text, nullable=False)
    derived: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    derivation: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON text
    observation_key: Mapped[str] = mapped_column(String(64), nullable=False)
    source_payload_hash: Mapped[str | None] = mapped_column(Text, nullable=True)
    first_detected_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    processed_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)


class IngestionRun(Base):
    __tablename__ = "ingestion_runs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    source: Mapped[str] = mapped_column(Text, nullable=False)
    started_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="running")
    companies_seen: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    filings_seen: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    facts_seen: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    inserted_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    sec_requests: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    sec_retries: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    sec_errors: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    sec_cached: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    sec_duration_ms: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)


class ApiKey(Base):
    __tablename__ = "api_keys"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    owner_email: Mapped[str] = mapped_column(Text, nullable=False)
    key_prefix: Mapped[str] = mapped_column(Text, nullable=False)
    key_hash: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    plan: Mapped[str] = mapped_column(Text, nullable=False, default="free")
    label: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)
    last_used_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)


class ApiUsage(Base):
    __tablename__ = "api_usage"
    __table_args__ = (
        Index("ix_api_usage_key_time", "api_key_id", "occurred_at"),
        Index("ix_api_usage_request_id", "request_id"),
    )

    id: Mapped[int] = mapped_column(BigSerial, primary_key=True, autoincrement=True)
    api_key_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("api_keys.id"), nullable=False)
    request_id: Mapped[str] = mapped_column(Text, nullable=False)
    route_template: Mapped[str] = mapped_column(Text, nullable=False)
    http_status: Mapped[int] = mapped_column(Integer, nullable=False)
    units: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    response_bytes: Mapped[int | None] = mapped_column(BigSerial, nullable=True)
    export_rows: Mapped[int | None] = mapped_column(Integer, nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)


class CompanyWatch(Base):
    __tablename__ = "company_watches"
    __table_args__ = (Index("ix_company_watches_cik_active", "cik", "is_active"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    api_key_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("api_keys.id"), nullable=False)
    cik: Mapped[str] = mapped_column(String(10), ForeignKey("companies.cik"), nullable=False)
    destination_type: Mapped[str] = mapped_column(Text, nullable=False)  # webhook | email
    destination: Mapped[str] = mapped_column(Text, nullable=False)
    secret_hash: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)
    deactivated_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    last_delivered_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)


class NotificationDelivery(Base):
    __tablename__ = "notification_deliveries"
    __table_args__ = (Index("ix_deliveries_status_next", "status", "next_attempt_at"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    watch_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("company_watches.id"), nullable=False
    )
    filing_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("filings.id"), nullable=False)
    event_id: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="pending")
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_status_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_error_redacted: Mapped[str | None] = mapped_column(Text, nullable=True)
    next_attempt_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)
    delivered_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)


class AuditEvent(Base):
    """Audit trail for key creation/revocation and watch changes."""

    __tablename__ = "audit_events"

    id: Mapped[int] = mapped_column(BigSerial, primary_key=True, autoincrement=True)
    actor: Mapped[str] = mapped_column(Text, nullable=False)  # api_key:<prefix> | admin | script
    action: Mapped[str] = mapped_column(Text, nullable=False)
    subject_type: Mapped[str] = mapped_column(Text, nullable=False)
    subject_id: Mapped[str] = mapped_column(Text, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)


class UniverseMember(Base):
    """A CIK this deployment aims to keep ingested. Drives bulk ingestion and polling."""

    __tablename__ = "universe_members"
    __table_args__ = (Index("ix_universe_due", "is_active", "priority", "next_attempt_at"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    cik: Mapped[str] = mapped_column(String(10), nullable=False, unique=True)
    source: Mapped[str] = mapped_column(Text, nullable=False)  # tickers | file | watch | manual
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=1000)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    disabled_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    added_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)
    last_attempt_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    last_success_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    next_attempt_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    consecutive_failures: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)


class DataQualitySnapshot(Base):
    """Point-in-time quality and coverage metrics, written at the end of each ingestion run."""

    __tablename__ = "data_quality_snapshots"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    taken_at: Mapped[datetime] = mapped_column(
        UTCDateTime, nullable=False, default=utcnow, index=True
    )
    companies_known: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    companies_ingested: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    companies_stale: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    filings_total: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    filings_with_accepted: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    duplicate_filings: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    facts_total: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    facts_ok: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    facts_partial: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    facts_ambiguous: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    facts_invalid: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    facts_with_provenance_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    pending_deliveries: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    delivered_24h: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failed_24h: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    oldest_pending_age_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    active_watches: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    universe_active: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    universe_due: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    universe_disabled: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    listings_total: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    listings_listed: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    listing_events_24h: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )


class KeyRequest(Base):
    """Self-serve API key request awaiting operator approval (or auto-approval via email)."""

    __tablename__ = "key_requests"
    __table_args__ = (Index("ix_key_requests_email_status", "email", "status"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(Text, nullable=False)
    use_case: Mapped[str] = mapped_column(Text, nullable=False)
    requested_plan: Mapped[str] = mapped_column(Text, nullable=False, default="free")
    status: Mapped[str] = mapped_column(Text, nullable=False, default="pending")
    client_ip_hash: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)
    approved_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    approved_key_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    rejected_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    key_delivered_via: Mapped[str | None] = mapped_column(Text, nullable=True)  # email | operator


# ---- International listings (Canada / Europe / UK) ----------------------------------------


class Market(Base):
    """A trading venue identified by its ISO 10383 MIC."""

    __tablename__ = "markets"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    mic: Mapped[str] = mapped_column(String(4), nullable=False, unique=True)
    operating_mic: Mapped[str | None] = mapped_column(String(4), nullable=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    country: Mapped[str] = mapped_column(String(2), nullable=False)  # ISO 3166-1 alpha-2
    region: Mapped[str] = mapped_column(Text, nullable=False)  # canada | europe | uk
    source: Mapped[str] = mapped_column(Text, nullable=False)  # esma_firds | fca_firds | tsx ...
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)


class Issuer(Base):
    """Legal entity behind listed instruments, keyed by LEI when known."""

    __tablename__ = "issuers"
    __table_args__ = (Index("ix_issuers_legal_name", "legal_name"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    lei: Mapped[str | None] = mapped_column(String(20), nullable=True, unique=True)
    legal_name: Mapped[str] = mapped_column(Text, nullable=False)
    country: Mapped[str | None] = mapped_column(String(2), nullable=True)
    jurisdiction: Mapped[str | None] = mapped_column(Text, nullable=True)
    registration_status: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[str] = mapped_column(Text, nullable=False)
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    first_detected_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)


class ListedInstrument(Base):
    """One instrument (ISIN) admitted to one venue (MIC); the unit of listing lifecycle."""

    __tablename__ = "listed_instruments"
    __table_args__ = (
        UniqueConstraint("listing_key", "mic", name="uq_listed_instruments_key_mic"),
        Index("ix_listed_instruments_isin", "isin"),
        Index("ix_listed_instruments_mic_status", "mic", "status"),
        Index("ix_listed_instruments_issuer_name", "issuer_name"),
        Index("ix_listed_instruments_issuer_lei", "issuer_lei"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    # ISIN when the source provides one; exchange feeds without ISINs are keyed by symbol.
    isin: Mapped[str | None] = mapped_column(String(12), nullable=True)
    listing_key: Mapped[str] = mapped_column(String(40), nullable=False)  # ISIN or SYM:<symbol>
    mic: Mapped[str] = mapped_column(String(4), ForeignKey("markets.mic"), nullable=False)
    issuer_name: Mapped[str] = mapped_column(Text, nullable=False)
    issuer_lei: Mapped[str | None] = mapped_column(String(20), nullable=True)
    symbol: Mapped[str | None] = mapped_column(Text, nullable=True)
    short_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    cfi_code: Mapped[str | None] = mapped_column(String(6), nullable=True)
    instrument_type: Mapped[str] = mapped_column(Text, nullable=False, default="share")
    currency: Mapped[str | None] = mapped_column(String(3), nullable=True)
    admission_requested_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    admission_approved_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    first_trade_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    termination_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(Text, nullable=False)  # listed | delisted | suspended
    source: Mapped[str] = mapped_column(Text, nullable=False)
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    source_record_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    source_published_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    first_detected_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    processed_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    quality_status: Mapped[str] = mapped_column(Text, nullable=False, default="ok")


class ListingEvent(Base):
    """Detected lifecycle change for an instrument on a venue, idempotent per key."""

    __tablename__ = "listing_events"
    __table_args__ = (
        UniqueConstraint("event_key", name="uq_listing_events_key"),
        Index("ix_listing_events_type_date", "event_type", "event_date"),
        Index("ix_listing_events_detected", "detected_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    instrument_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("listed_instruments.id"), nullable=False
    )
    isin: Mapped[str | None] = mapped_column(String(12), nullable=True)
    listing_key: Mapped[str] = mapped_column(String(40), nullable=False)
    symbol: Mapped[str | None] = mapped_column(Text, nullable=True)
    mic: Mapped[str] = mapped_column(String(4), nullable=False)
    issuer_name: Mapped[str] = mapped_column(Text, nullable=False)
    event_type: Mapped[str] = mapped_column(Text, nullable=False)
    event_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    event_key: Mapped[str] = mapped_column(String(64), nullable=False)
    source: Mapped[str] = mapped_column(Text, nullable=False)
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    details: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON text
    detected_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    quality_status: Mapped[str] = mapped_column(Text, nullable=False, default="ok")


class MarketSourceFile(Base):
    """Register/exchange files already processed, so daily deltas are parsed once."""

    __tablename__ = "market_source_files"
    __table_args__ = (UniqueConstraint("source", "file_name", name="uq_market_source_files"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    source: Mapped[str] = mapped_column(Text, nullable=False)
    file_name: Mapped[str] = mapped_column(Text, nullable=False)
    file_type: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="done")
    records_seen: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    records_ingested: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    processed_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)
