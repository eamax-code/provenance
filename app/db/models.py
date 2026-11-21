"""SQLAlchemy models. See docs/data-dictionary.md for field meaning."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import (
    DDL,
    BigInteger,
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
    event,
    func,
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
    # Identity the SEC publishes in the submissions (issue #9); empty strings are stored as null.
    filer_category: Mapped[str | None] = mapped_column(Text, nullable=True)  # Large accelerated…
    sec_office: Mapped[str | None] = mapped_column(Text, nullable=True)  # ownerOrg
    ein: Mapped[str | None] = mapped_column(String(9), nullable=True)
    lei: Mapped[str | None] = mapped_column(String(20), nullable=True)
    phone: Mapped[str | None] = mapped_column(Text, nullable=True)
    website: Mapped[str | None] = mapped_column(Text, nullable=True)
    investor_website: Mapped[str | None] = mapped_column(Text, nullable=True)
    business_address: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON
    mailing_address: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON
    tickers: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON list
    exchanges: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON list
    insider_filings_as_issuer: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    insider_filings_as_owner: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
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
        Index("ix_filings_stream_status", "stream_status"),
        Index("ix_filings_stream_at", "stream_at"),
        Index("ix_filings_form_date", "form_type", "filing_date"),
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
    items: Mapped[str | None] = mapped_column(Text, nullable=True)  # 8-K items, "5.02,9.01"
    # Event types that need more than the form to tell (sec.ipo_priced: the company's first
    # final prospectus after its registration), set at ingestion; comma-separated
    event_tags: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    source_payload_hash: Mapped[str | None] = mapped_column(Text, nullable=True)
    first_detected_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    processed_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    ingestion_run_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    quality_status: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)
    # Event feed (ADR 0007): pending -> published once committed; backfill rows are skipped.
    stream_status: Mapped[str] = mapped_column(
        Text, nullable=False, default="skipped", server_default="skipped"
    )
    stream_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)


class FinancialFact(Base):
    __tablename__ = "financial_facts"
    __table_args__ = (
        UniqueConstraint("cik", "observation_key", name="uq_financial_facts_cik_observation_key"),
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
    # JSON {"submissions 200": n, "archives 404": n, ...}: SEC responses by endpoint and status
    sec_by_endpoint: Mapped[str | None] = mapped_column(Text, nullable=True)
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
    # The reader's theme in chat and the Explorer (GH #12); null means the site's dark theme.
    ui_theme: Mapped[str | None] = mapped_column(Text, nullable=True)


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
    # Comma-separated filing event types (D-05); null means every new filing.
    event_types: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)
    deactivated_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    last_delivered_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)


class ListingWatch(Base):
    """A key holder's subscription to listing events on a venue, country or region (ticket 09)."""

    __tablename__ = "listing_watches"
    __table_args__ = (
        Index("ix_listing_watches_scope_active", "scope_type", "scope_value", "is_active"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    api_key_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("api_keys.id"), nullable=False)
    scope_type: Mapped[str] = mapped_column(Text, nullable=False)  # mic | country | region
    scope_value: Mapped[str] = mapped_column(Text, nullable=False)  # XPAR | FR | europe
    event_types: Mapped[str] = mapped_column(Text, nullable=False)  # comma-separated
    destination_type: Mapped[str] = mapped_column(Text, nullable=False)  # webhook | email
    destination: Mapped[str] = mapped_column(Text, nullable=False)
    secret_hash: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)
    deactivated_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    last_delivered_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)


class IpoTerms(Base):
    """Deal terms read from one prospectus (launch plan F-02): each value with its evidence."""

    __tablename__ = "ipo_terms"
    __table_args__ = (Index("ix_ipo_terms_cik", "cik"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    cik: Mapped[str] = mapped_column(String(10), nullable=False)
    accession_number: Mapped[str] = mapped_column(String(25), nullable=False, unique=True)
    form_type: Mapped[str] = mapped_column(Text, nullable=False)
    filing_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    terms: Mapped[str] = mapped_column(Text, nullable=False)  # JSON {field: {value, evidence}}
    extractor_version: Mapped[str] = mapped_column(Text, nullable=False)
    extracted_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)


class TypeWatch(Base):
    """A key holder's subscription to filing event types across companies (launch plan T-01):
    "any restatement", optionally narrowed to a universe. High-volume types without a universe
    are delivered as one batch an hour so earnings season cannot flood a receiver."""

    __tablename__ = "type_watches"
    __table_args__ = (Index("ix_type_watches_active", "is_active"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    api_key_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("api_keys.id"), nullable=False)
    event_types: Mapped[str] = mapped_column(Text, nullable=False)  # comma-separated
    sic_prefix: Mapped[str | None] = mapped_column(Text, nullable=True)  # "28", "2834"
    exchange: Mapped[str | None] = mapped_column(Text, nullable=True)  # "Nasdaq", "NYSE"
    filer_category: Mapped[str | None] = mapped_column(Text, nullable=True)
    ciks: Mapped[str | None] = mapped_column(Text, nullable=True)  # comma-separated, <= 500
    delivery_mode: Mapped[str] = mapped_column(Text, nullable=False)  # immediate | hourly
    destination_type: Mapped[str] = mapped_column(Text, nullable=False)  # webhook
    destination: Mapped[str] = mapped_column(Text, nullable=False)
    secret_hash: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)
    deactivated_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    last_delivered_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)


class NotificationDelivery(Base):
    """One event to one watch: a filing for a company watch, or a listing event for a listing
    watch. Exactly one of the two pairs of ids is set."""

    __tablename__ = "notification_deliveries"
    __table_args__ = (Index("ix_deliveries_status_next", "status", "next_attempt_at"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    watch_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("company_watches.id"), nullable=True
    )
    filing_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("filings.id"), nullable=True
    )
    listing_watch_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("listing_watches.id"), nullable=True
    )
    listing_event_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("listing_events.id"), nullable=True
    )
    type_watch_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("type_watches.id"), nullable=True
    )
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
    # Filings first detected in the 24 hours before the snapshot: seconds from first detection to
    # processing, median and 95th percentile, and how many filings that is.
    detect_to_process_p50_s: Mapped[int | None] = mapped_column(Integer, nullable=True)
    detect_to_process_p95_s: Mapped[int | None] = mapped_column(Integer, nullable=True)
    processed_24h: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # The same filings: seconds from the SEC's acceptance to first detection here, i.e. how long
    # after it was filed a filing reached Provenance (only filings with an acceptance time).
    accept_to_detect_p50_s: Mapped[int | None] = mapped_column(Integer, nullable=True)
    accept_to_detect_p95_s: Mapped[int | None] = mapped_column(Integer, nullable=True)
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
    # Admission requested by the issuer (FIRDS IssrReq); None where the source does not say.
    issuer_requested: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
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
        Index("ix_listing_events_stream_status", "stream_status"),
        Index("ix_listing_events_stream_at", "stream_at"),
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
    # Event feed (ADR 0007): stamped with stream_at after the ingesting transaction commits.
    stream_status: Mapped[str] = mapped_column(
        Text, nullable=False, default="pending", server_default="published"
    )
    stream_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)


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


class FilingSection(Base):
    """One item of a filing's text, fetched once and kept so it can be re-read without SEC."""

    __tablename__ = "filing_sections"
    __table_args__ = (
        UniqueConstraint("accession_number", "item", name="uq_filing_sections_accession_item"),
        Index("ix_filing_sections_cik", "cik"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    cik: Mapped[str] = mapped_column(String(10), nullable=False)
    accession_number: Mapped[str] = mapped_column(String(25), nullable=False)
    item: Mapped[str] = mapped_column(String(10), nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)  # ok, no_section, fetch_failed
    text: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)
    # Extraction from the text, rerun when the extractor version changes.
    extractor_version: Mapped[str | None] = mapped_column(Text, nullable=True)
    extraction_status: Mapped[str | None] = mapped_column(Text, nullable=True)  # ok, failed
    extracted_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    model: Mapped[str | None] = mapped_column(Text, nullable=True)


class OfficerChange(Base):
    """A change of a director or officer read from an 8-K item 5.02, with its evidence."""

    __tablename__ = "officer_changes"
    __table_args__ = (
        UniqueConstraint("accession_number", "seq", name="uq_officer_changes_accession_seq"),
        Index("ix_officer_changes_cik_filing_date", "cik", "filing_date"),
        Index("ix_officer_changes_stream_at", "stream_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    cik: Mapped[str] = mapped_column(String(10), nullable=False)
    accession_number: Mapped[str] = mapped_column(String(25), nullable=False)
    filing_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    person: Mapped[str | None] = mapped_column(Text, nullable=True)
    role: Mapped[str | None] = mapped_column(Text, nullable=True)
    change_type: Mapped[str] = mapped_column(Text, nullable=False)
    what: Mapped[str | None] = mapped_column(Text, nullable=True)
    effective: Mapped[str | None] = mapped_column(Text, nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    successor: Mapped[str | None] = mapped_column(Text, nullable=True)
    evidence: Mapped[str | None] = mapped_column(Text, nullable=True)
    verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    extractor_version: Mapped[str] = mapped_column(Text, nullable=False)
    model: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Event feed (ADR 0007): changes read from now on are published as sec.officer_change events.
    # Rows read before the feed carried them default to published without a stream time, so
    # they never appear as new.
    stream_status: Mapped[str] = mapped_column(
        Text, nullable=False, default="pending", server_default="published"
    )
    stream_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    # JSON: company and peer figures as filed by the filing date (app.services.leadership_context)
    context: Mapped[str | None] = mapped_column(Text, nullable=True)
    extracted_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)


class ChatSession(Base):
    """A saved chat conversation; owned by one API key, never by the public demo key."""

    __tablename__ = "chat_sessions"
    __table_args__ = (Index("ix_chat_sessions_key_updated", "api_key_id", "updated_at"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    api_key_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("api_keys.id", ondelete="CASCADE"), nullable=False
    )
    title: Mapped[str] = mapped_column(Text, nullable=False)
    company_cik: Mapped[str | None] = mapped_column(String(10), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)


class ChatMessage(Base):
    __tablename__ = "chat_messages"
    __table_args__ = (Index("ix_chat_messages_session_seq", "session_id", "seq"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("chat_sessions.id", ondelete="CASCADE"), nullable=False
    )
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    role: Mapped[str] = mapped_column(Text, nullable=False)  # user, assistant
    content: Mapped[str] = mapped_column(Text, nullable=False)
    reply: Mapped[str | None] = mapped_column(Text, nullable=True)  # assistant: JSON reply
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)


class MartCompany(Base):
    """One row per company, precomputed for quick answers (issue #8; #3 step 1).

    Rebuilt from companies, filings and financial_facts by app.services.marts. Every figure keeps
    the accession number and filing link it came from."""

    __tablename__ = "mart_company"
    __table_args__ = (
        Index("ix_mart_company_ipo_date", "ipo_prospectus_date"),
        Index("ix_mart_company_registration", "first_registration_date"),
        Index("ix_mart_company_latest_filing", "latest_filing_date"),
        Index("ix_mart_company_revenue", "latest_revenue"),
    )

    cik: Mapped[str] = mapped_column(String(10), primary_key=True)
    legal_name: Mapped[str] = mapped_column(Text, nullable=False)
    ticker: Mapped[str | None] = mapped_column(Text, nullable=True)
    exchange: Mapped[str | None] = mapped_column(Text, nullable=True)
    sic_code: Mapped[str | None] = mapped_column(Text, nullable=True)
    sic_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    first_filing_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    latest_filing_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    filings_last_12_months: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Going public: the first registration statement (S-1/F-1) and final prospectus (424B4).
    first_registration_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    first_registration_form: Mapped[str | None] = mapped_column(Text, nullable=True)
    ipo_prospectus_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    ipo_prospectus_accession: Mapped[str | None] = mapped_column(String(25), nullable=True)
    ipo_prospectus_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    latest_annual_report_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    latest_annual_report_form: Mapped[str | None] = mapped_column(Text, nullable=True)
    latest_revenue: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    latest_revenue_period_end: Mapped[date | None] = mapped_column(Date, nullable=True)
    # JSON text: {metric: {value, unit, period_end, form_type, filed_date, accession, url}}
    latest_annual: Mapped[str | None] = mapped_column(Text, nullable=True)
    # JSON text: up to five fiscal years of revenue, newest first, each with its filing.
    revenue_history: Mapped[str | None] = mapped_column(Text, nullable=True)
    built_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)


class MartFilingActivity(Base):
    """Filings per month and form, with the number of companies that filed them (issue #8)."""

    __tablename__ = "mart_filing_activity"

    month: Mapped[date] = mapped_column(Date, primary_key=True)  # first day of the month
    form_type: Mapped[str] = mapped_column(Text, primary_key=True)
    filings: Mapped[int] = mapped_column(Integer, nullable=False)
    companies: Mapped[int] = mapped_column(Integer, nullable=False)


class MartFinancial(Base):
    """One reported value per company, metric, period and unit: the annual report's observation
    for its period when there is one, else the latest filed (issue #3). Derived quarters stay
    out (ADR 0003); point-in-time questions read financial_facts (ADR 0009)."""

    __tablename__ = "mart_financials"
    __table_args__ = (
        # Covers the screen's ranking (value included), so it reads no table pages.
        Index(
            "ix_mart_financials_screen",
            "metric",
            "period_class",
            "unit",
            "period_end",
            "cik",
            postgresql_include=["value"],
        ),
        Index("ix_mart_financials_company", "cik", "metric", "period_class", "period_end"),
    )

    cik: Mapped[str] = mapped_column(String(10), primary_key=True)
    metric: Mapped[str] = mapped_column(Text, primary_key=True)
    period_class: Mapped[str] = mapped_column(Text, primary_key=True)  # annual | quarterly
    unit: Mapped[str] = mapped_column(Text, primary_key=True)
    period_end: Mapped[date] = mapped_column(Date, primary_key=True)
    period_start: Mapped[date | None] = mapped_column(Date, nullable=True)
    value: Mapped[Decimal] = mapped_column(Numeric, nullable=False)
    currency: Mapped[str | None] = mapped_column(Text, nullable=True)
    fiscal_year: Mapped[int] = mapped_column(Integer, nullable=False)  # app.services.periods
    fiscal_quarter: Mapped[int | None] = mapped_column(Integer, nullable=True)
    form_type: Mapped[str | None] = mapped_column(Text, nullable=True)
    filed_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    accession_number: Mapped[str | None] = mapped_column(String(25), nullable=True)
    source_tag: Mapped[str] = mapped_column(Text, nullable=False)
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    quality_status: Mapped[str] = mapped_column(Text, nullable=False)
    mapping_version: Mapped[str] = mapped_column(Text, nullable=False)


class MartCompanyPeriod(Base):
    """One row per company and fiscal year with the five annual figures side by side, for
    exports and quick reads (issue #3). `sources` holds each figure's filing link."""

    __tablename__ = "mart_company_period"

    cik: Mapped[str] = mapped_column(String(10), primary_key=True)
    fiscal_year: Mapped[int] = mapped_column(Integer, primary_key=True)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)
    revenue: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    operating_income: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    net_income: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    total_assets: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    operating_cash_flow: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    sources: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON {metric: url}


class CompanyDocument(Base):
    """A readable document about a company, built from the marts (issue #3). On PostgreSQL a
    generated search_vector makes the documents searchable across companies."""

    __tablename__ = "company_documents"

    cik: Mapped[str] = mapped_column(String(10), primary_key=True)
    kind: Mapped[str] = mapped_column(Text, primary_key=True)  # profile
    title: Mapped[str] = mapped_column(Text, nullable=False)
    markdown: Mapped[str] = mapped_column(Text, nullable=False)
    built_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)


class RateLimitCounter(Base):
    """Requests counted in one fixed window, for rate limits shared by every API replica."""

    __tablename__ = "rate_limit_counters"

    key: Mapped[str] = mapped_column(Text, primary_key=True)  # "<limiter>:<api key id or ip>"
    window_start: Mapped[int] = mapped_column(BigInteger, primary_key=True)  # epoch seconds
    count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class CompanyAlias(Base):
    """Another name a company is found by (issue #3, step 2). Today the former names the SEC
    lists for the company ("Facebook Inc" for Meta Platforms), with the dates each was used."""

    __tablename__ = "company_aliases"

    cik: Mapped[str] = mapped_column(String(10), primary_key=True)
    alias: Mapped[str] = mapped_column(Text, primary_key=True)
    kind: Mapped[str] = mapped_column(Text, nullable=False, default="former")
    valid_from: Mapped[date | None] = mapped_column(Date, nullable=True)
    valid_to: Mapped[date | None] = mapped_column(Date, nullable=True)


Index("ix_company_aliases_lower", func.lower(CompanyAlias.alias))


class Account(Base):
    """A person who signed in with their email (GH #15). Their API keys are the keys issued to
    that email, including keys an operator issued before accounts existed."""

    __tablename__ = "accounts"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(Text, nullable=False, unique=True)  # lower case
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)
    last_sign_in_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    ui_theme: Mapped[str | None] = mapped_column(Text, nullable=True)


class SignInToken(Base):
    """A one-time sign-in link. Only its hash is stored; it lasts minutes and works once."""

    __tablename__ = "sign_in_tokens"
    __table_args__ = (Index("ix_sign_in_tokens_email_created", "email", "created_at"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(Text, nullable=False)
    token_hash: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)


class AccountSession(Base):
    """A signed-in browser. The cookie holds a random token; only its hash is stored."""

    __tablename__ = "account_sessions"
    __table_args__ = (Index("ix_account_sessions_account", "account_id"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    account_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("accounts.id"), nullable=False)
    token_hash: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    last_seen_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)


# Search structures that exist only on PostgreSQL. The migrations f1b7c3a9d2e5 and b9d4e2f7a6c1
# create them on real databases; these hooks give a schema built from the models (a PostgreSQL test
# database) the same ones. SQLite skips them and the lookups fall back to scans.
event.listen(
    Company.__table__,
    "after_create",
    DDL(
        "CREATE EXTENSION IF NOT EXISTS pg_trgm; "
        "CREATE INDEX IF NOT EXISTS ix_companies_legal_name_trgm "
        "ON companies USING gin (lower(legal_name) gin_trgm_ops); "
        "CREATE INDEX IF NOT EXISTS ix_companies_ticker_upper ON companies (upper(ticker))"
    ).execute_if(dialect="postgresql"),
)
event.listen(
    FilingSection.__table__,
    "after_create",
    DDL(
        "ALTER TABLE filing_sections ADD COLUMN IF NOT EXISTS search_vector tsvector "
        "GENERATED ALWAYS AS (to_tsvector('english'::regconfig, COALESCE(text, ''::text))) STORED; "
        "CREATE INDEX IF NOT EXISTS ix_filing_sections_search_vector "
        "ON filing_sections USING gin (search_vector)"
    ).execute_if(dialect="postgresql"),
)


def _create_chunks(target, connection, **kw):
    """section_chunks (pgvector) for a PostgreSQL schema built from the models; skipped where
    the database is not PostgreSQL or the vector extension is not installed."""
    if connection.dialect.name != "postgresql":
        return
    from sqlalchemy import text

    from app.db.search_ddl import CHUNKS_DDL

    if connection.execute(
        text("SELECT 1 FROM pg_available_extensions WHERE name = 'vector'")
    ).first():
        connection.exec_driver_sql(CHUNKS_DDL)


def _drop_chunks(target, connection, **kw):
    if connection.dialect.name == "postgresql":
        connection.exec_driver_sql("DROP TABLE IF EXISTS section_chunks")


event.listen(FilingSection.__table__, "after_create", _create_chunks)
event.listen(
    CompanyDocument.__table__,
    "after_create",
    DDL(
        "ALTER TABLE company_documents ADD COLUMN IF NOT EXISTS search_vector tsvector "
        "GENERATED ALWAYS AS (to_tsvector('english'::regconfig, title || ' ' || markdown)) STORED; "
        "CREATE INDEX IF NOT EXISTS ix_company_documents_search "
        "ON company_documents USING gin (search_vector)"
    ).execute_if(dialect="postgresql"),
)
event.listen(FilingSection.__table__, "before_drop", _drop_chunks)


# ---- connections graph: insiders, subsidiaries, beneficial owners (GH #24, ADR 0011) ------


class InsiderFiling(Base):
    """One reporting owner on one Form 3, 4 or 5, from the SEC's insider transaction data sets
    or, for filings newer than the latest data set, from the filing's own XML. Owner names and
    roles are kept; owner street addresses are never stored."""

    __tablename__ = "insider_filings"
    __table_args__ = (
        UniqueConstraint("accession_number", "owner_cik", name="uq_insider_filings_acc_owner"),
        Index("ix_insider_filings_issuer_date", "issuer_cik", "filing_date"),
        Index("ix_insider_filings_owner_date", "owner_cik", "filing_date"),
    )

    id: Mapped[int] = mapped_column(BigSerial, primary_key=True, autoincrement=True)
    accession_number: Mapped[str] = mapped_column(String(25), nullable=False)
    issuer_cik: Mapped[str] = mapped_column(String(10), nullable=False)
    owner_cik: Mapped[str] = mapped_column(String(10), nullable=False)
    owner_name: Mapped[str] = mapped_column(Text, nullable=False)  # as filed, "COOK TIMOTHY D"
    is_director: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_officer: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_ten_percent_owner: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_other: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    officer_title: Mapped[str | None] = mapped_column(Text, nullable=True)
    other_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    form_type: Mapped[str] = mapped_column(Text, nullable=False)
    filing_date: Mapped[date] = mapped_column(Date, nullable=False)
    period_of_report: Mapped[date | None] = mapped_column(Date, nullable=True)
    plan_10b5_1: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    source: Mapped[str] = mapped_column(Text, nullable=False)  # "dataset:2025q3" or "filing"


class InsiderTransaction(Base):
    """A transaction or holding row of a Form 3, 4 or 5 (table I non-derivative, table II
    derivative). Rows belong to the filing; a joint filing's rows are shared by its owners."""

    __tablename__ = "insider_transactions"
    __table_args__ = (
        UniqueConstraint(
            "accession_number",
            "row_kind",
            "is_derivative",
            "row_key",
            name="uq_insider_transactions_row",
        ),  # fmt: skip
        Index("ix_insider_transactions_issuer_date", "issuer_cik", "trans_date"),
    )

    id: Mapped[int] = mapped_column(BigSerial, primary_key=True, autoincrement=True)
    accession_number: Mapped[str] = mapped_column(String(25), nullable=False)
    issuer_cik: Mapped[str] = mapped_column(String(10), nullable=False)
    row_kind: Mapped[str] = mapped_column(Text, nullable=False)  # transaction, holding
    is_derivative: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    row_key: Mapped[str] = mapped_column(Text, nullable=False)
    security_title: Mapped[str | None] = mapped_column(Text, nullable=True)
    trans_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    trans_code: Mapped[str | None] = mapped_column(String(4), nullable=True)
    shares: Mapped[Decimal | None] = mapped_column(Numeric(24, 4), nullable=True)
    price: Mapped[Decimal | None] = mapped_column(Numeric(24, 6), nullable=True)
    acquired_disposed: Mapped[str | None] = mapped_column(String(1), nullable=True)
    shares_after: Mapped[Decimal | None] = mapped_column(Numeric(24, 4), nullable=True)
    direct_indirect: Mapped[str | None] = mapped_column(String(1), nullable=True)
    nature_of_ownership: Mapped[str | None] = mapped_column(Text, nullable=True)
    underlying_title: Mapped[str | None] = mapped_column(Text, nullable=True)
    underlying_shares: Mapped[Decimal | None] = mapped_column(Numeric(24, 4), nullable=True)
    exercise_price: Mapped[Decimal | None] = mapped_column(Numeric(24, 6), nullable=True)


class InsiderDataset(Base):
    """A quarterly insider transaction data set loaded from the SEC."""

    __tablename__ = "insider_datasets"

    quarter: Mapped[str] = mapped_column(String(6), primary_key=True)  # "2025q3"
    sha256: Mapped[str] = mapped_column(Text, nullable=False)
    filings: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_filing_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    loaded_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)


class Subsidiary(Base):
    """A subsidiary listed in a 10-K exhibit 21 (or a 20-F exhibit 8), one row per line."""

    __tablename__ = "subsidiaries"
    __table_args__ = (
        UniqueConstraint("cik", "accession_number", "position", name="uq_subsidiaries_row"),
        Index("ix_subsidiaries_cik_date", "cik", "filing_date"),
    )

    id: Mapped[int] = mapped_column(BigSerial, primary_key=True, autoincrement=True)
    cik: Mapped[str] = mapped_column(String(10), nullable=False)
    accession_number: Mapped[str] = mapped_column(String(25), nullable=False)
    form_type: Mapped[str] = mapped_column(Text, nullable=False)
    filing_date: Mapped[date] = mapped_column(Date, nullable=False)
    exhibit: Mapped[str] = mapped_column(Text, nullable=False)  # "EX-21.1"
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    jurisdiction: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_url: Mapped[str] = mapped_column(Text, nullable=False)  # the exhibit document


class BeneficialOwner(Base):
    """A reporting person on a Schedule 13D or 13G about a company, with the stake it reports."""

    __tablename__ = "beneficial_owners"
    __table_args__ = (
        UniqueConstraint(
            "subject_cik", "accession_number", "position", name="uq_beneficial_owners_row"
        ),
        Index("ix_beneficial_owners_subject_date", "subject_cik", "filing_date"),
        Index("ix_beneficial_owners_filer", "filer_cik"),
    )

    id: Mapped[int] = mapped_column(BigSerial, primary_key=True, autoincrement=True)
    subject_cik: Mapped[str] = mapped_column(String(10), nullable=False)
    accession_number: Mapped[str] = mapped_column(String(25), nullable=False)
    form_type: Mapped[str] = mapped_column(Text, nullable=False)
    filing_date: Mapped[date] = mapped_column(Date, nullable=False)
    event_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    filer_cik: Mapped[str | None] = mapped_column(String(10), nullable=True)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    holder_name: Mapped[str] = mapped_column(Text, nullable=False)
    holder_cik: Mapped[str | None] = mapped_column(String(10), nullable=True)
    holder_type: Mapped[str | None] = mapped_column(Text, nullable=True)  # IA, CO, IN, ...
    shares: Mapped[Decimal | None] = mapped_column(Numeric(24, 4), nullable=True)
    percent: Mapped[Decimal | None] = mapped_column(Numeric(9, 4), nullable=True)
    source_url: Mapped[str] = mapped_column(Text, nullable=False)  # the filing


class GraphSourceState(Base):
    """When a company's exhibit 21, 13D/G filings or recent insider filings were last read."""

    __tablename__ = "graph_source_state"

    cik: Mapped[str] = mapped_column(String(10), primary_key=True)
    kind: Mapped[str] = mapped_column(Text, primary_key=True)  # subsidiaries, holders, insiders
    checked_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)
    status: Mapped[str] = mapped_column(Text, nullable=False)  # ok, none, failed
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)


# ---- filings tracker: every filing EDGAR disseminates, read hourly (ADR 0012) --------------


class EdgarFeedEntry(Base):
    """One filing as EDGAR lists it, per company it names (a Form 4 names its issuer)."""

    __tablename__ = "edgar_feed"
    __table_args__ = (
        UniqueConstraint("accession_number", "cik", name="uq_edgar_feed_accession_cik"),
        Index("ix_edgar_feed_status", "status"),
        Index("ix_edgar_feed_cik", "cik"),
        Index("ix_edgar_feed_form_date", "form_type", "filing_date"),
    )

    id: Mapped[int] = mapped_column(BigSerial, primary_key=True, autoincrement=True)
    accession_number: Mapped[str] = mapped_column(String(25), nullable=False)
    cik: Mapped[str] = mapped_column(String(10), nullable=False)
    company_name: Mapped[str] = mapped_column(Text, nullable=False)
    form_type: Mapped[str] = mapped_column(Text, nullable=False)
    role: Mapped[str] = mapped_column(Text, nullable=False)  # filer, subject, issuer, listed
    filing_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    accepted_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    source: Mapped[str] = mapped_column(Text, nullable=False)  # latest | daily-index
    seen_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)
    # new -> refreshed (a covered company) | discovered (added to coverage) | ignored | failed
    status: Mapped[str] = mapped_column(Text, nullable=False, default="new")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    handled_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)


class JobState(Base):
    """A scheduled job's progress marker, such as the last daily index read."""

    __tablename__ = "job_state"

    name: Mapped[str] = mapped_column(Text, primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)
