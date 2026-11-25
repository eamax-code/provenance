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
    text,
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
    # K-06: dei:EntityRegistrantName from the latest report's cover, exactly as filed
    registrant_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    registrant_name_accession: Mapped[str | None] = mapped_column(String(25), nullable=True)
    ticker: Mapped[str | None] = mapped_column(Text, nullable=True)
    exchange: Mapped[str | None] = mapped_column(Text, nullable=True)
    sic_code: Mapped[str | None] = mapped_column(Text, nullable=True)
    sic_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    entity_type: Mapped[str | None] = mapped_column(Text, nullable=True)
    state_of_incorporation: Mapped[str | None] = mapped_column(Text, nullable=True)
    # where it comes from: "dei:EntityIncorporationStateCountryCode" (the company's own cover tag,
    # with the filing) or "submissions" (the SEC's field, which can hold a home state: HubSpot)
    state_of_incorporation_source: Mapped[str | None] = mapped_column(Text, nullable=True)
    # the cover tag's value, beside the SEC field (state_of_incorporation) rather than over it
    state_of_incorporation_cover: Mapped[str | None] = mapped_column(Text, nullable=True)
    state_of_incorporation_accession: Mapped[str | None] = mapped_column(String(25), nullable=True)
    fiscal_year_end: Mapped[str | None] = mapped_column(Text, nullable=True)
    # S-05: years to add to the end-year fiscal label, as the latest 10-K words it (-1: the year
    # is named by the calendar year it starts in); null: not read, the end-year rule applies
    fiscal_year_offset: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # S-07: the company's own fiscal year ends (ISO dates, comma-separated, oldest first): the
    # year each annual report covers; a period takes the fiscal year in force when it was filed
    fiscal_year_ends: Mapped[str | None] = mapped_column(Text, nullable=True)
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
        Index("ix_filings_accession", "accession_number"),  # co-registrants (K-03)
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


class DividendFact(Base):
    """Q-04: dividends declared per share (CommonStockDividendsPerShareDeclared, else ...CashPaid),
    every filing's observation, normalized by the same code as financial_facts (same columns,
    period classes, fiscal labels and quality flags). A known exception to the mapping: kept
    apart so that adding it needed no mapping version bump; mapping 1.6.0 can fold it in."""

    __tablename__ = "dividend_facts"
    __table_args__ = (
        UniqueConstraint("cik", "observation_key", name="uq_dividend_facts_cik_observation_key"),
        Index("ix_dividend_facts_cik_period_end", "cik", "period_end"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    cik: Mapped[str] = mapped_column(String(10), nullable=False)
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
    # paused (A-01): still the customer's watch and counted, but nothing is sent or queued
    paused: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
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
    # paused (A-01): still the customer's watch and counted, but nothing is sent or queued
    paused: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
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


class InsiderActivity(Base):
    """Insider activity found by rules in Forms 4 (launch plan F-03): cluster buying, a first
    open-market purchase in two years, a large sale outside a 10b5-1 plan. Information about
    what insiders did, never a recommendation."""

    __tablename__ = "insider_activity"
    __table_args__ = (
        UniqueConstraint("activity_type", "cik", "accession_number", name="uq_insider_activity"),
        Index("ix_insider_activity_cik_date", "cik", "activity_date"),
        Index("ix_insider_activity_stream", "stream_status", "stream_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    cik: Mapped[str] = mapped_column(String(10), nullable=False)  # the issuer
    activity_type: Mapped[str] = mapped_column(Text, nullable=False)
    activity_date: Mapped[date] = mapped_column(Date, nullable=False)  # the trade that made it so
    filing_date: Mapped[date] = mapped_column(Date, nullable=False)
    accession_number: Mapped[str] = mapped_column(String(25), nullable=False)
    owners: Mapped[str] = mapped_column(Text, nullable=False)  # JSON [{owner_cik, name, role}]
    detail: Mapped[str] = mapped_column(Text, nullable=False)  # JSON, rule specific
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    stream_status: Mapped[str] = mapped_column(Text, nullable=False, default="skipped")
    stream_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)
    # F-03c: a rule change retracts an event (never deletes it) or corrects it in place
    status: Mapped[str] = mapped_column(Text, nullable=False, default="active",
                                        server_default="active")  # fmt: skip
    retracted_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    retraction_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    corrected_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    previous_values: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON


class InsiderFilingText(Base):
    """F-03d: the signatures, remarks and footnotes of a Form 3/4/5 that has an entity reporting
    owner (SEC insider data sets), read to link a fund to the individual who controls it."""

    __tablename__ = "insider_filing_text"

    accession_number: Mapped[str] = mapped_column(String(25), primary_key=True)
    signatures: Mapped[str] = mapped_column(Text, nullable=False)  # JSON list, as signed
    remarks: Mapped[str | None] = mapped_column(Text, nullable=True)
    footnotes: Mapped[str] = mapped_column(Text, nullable=False)  # JSON list of texts
    source: Mapped[str] = mapped_column(Text, nullable=False)


class FirstReported(Base):
    """A figure an 8-K item 2.02 earnings release stated before the 10-Q or 10-K that reported
    it (launch plan E-2): the same value, at the release's stated precision, on a line labelled
    for the metric. Point-in-time queries count the figure as known from the release date."""

    __tablename__ = "first_reported"
    __table_args__ = (
        UniqueConstraint("cik", "metric", "unit", "period_start", "period_end", "fact_accession",
                         name="uq_first_reported_fact"),
        Index("ix_first_reported_fact", "fact_accession", "metric"),
    )  # fmt: skip

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    cik: Mapped[str] = mapped_column(String(10), nullable=False)
    metric: Mapped[str] = mapped_column(Text, nullable=False)
    unit: Mapped[str] = mapped_column(Text, nullable=False)
    period_start: Mapped[date | None] = mapped_column(Date, nullable=True)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)
    value: Mapped[Decimal] = mapped_column(Numeric(38, 6), nullable=False)
    fact_accession: Mapped[str] = mapped_column(String(25), nullable=False)  # the 10-Q or 10-K
    release_accession: Mapped[str] = mapped_column(String(25), nullable=False)
    release_filing_date: Mapped[date] = mapped_column(Date, nullable=False)
    release_url: Mapped[str] = mapped_column(Text, nullable=False)  # the exhibit 99.1 document
    stated_as: Mapped[str] = mapped_column(Text, nullable=False)  # millions, thousands, ...
    evidence: Mapped[str] = mapped_column(Text, nullable=False)  # the line, as printed
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)


class CompanyAuditor(Base):
    """The audit firm named in an annual report's cover tags (launch plan E-3): dei:AuditorName,
    AuditorFirmId (the PCAOB firm ID) and AuditorLocation, from the SEC's Financial Statement
    and Notes data sets. A report after a change of auditor names both firms; `audited_through`
    is the end of the period each one audited."""

    __tablename__ = "company_auditors"
    __table_args__ = (Index("ix_company_auditors_cik_filed", "cik", "filed_date"),)

    accession_number: Mapped[str] = mapped_column(String(25), primary_key=True)
    auditor_key: Mapped[str] = mapped_column(Text, primary_key=True)  # firm ID, else the name
    cik: Mapped[str] = mapped_column(String(10), nullable=False)
    form_type: Mapped[str] = mapped_column(Text, nullable=False)
    fiscal_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    period_end: Mapped[date | None] = mapped_column(Date, nullable=True)  # the report's period
    audited_through: Mapped[date | None] = mapped_column(Date, nullable=True)
    filed_date: Mapped[date] = mapped_column(Date, nullable=False)
    auditor_name: Mapped[str] = mapped_column(Text, nullable=False)
    pcaob_firm_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    auditor_location: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[str] = mapped_column(Text, nullable=False)


class RegistrantSuccession(Base):
    """A company that continues under a new registrant (launch plan K-05), such as a new
    holding company. Facts stay under the CIK that filed them; readers join at query time."""

    __tablename__ = "registrant_successions"
    __table_args__ = (Index("ix_registrant_successions_successor", "successor_cik"),)

    predecessor_cik: Mapped[str] = mapped_column(String(10), primary_key=True)
    successor_cik: Mapped[str] = mapped_column(String(10), primary_key=True)
    effective_date: Mapped[date] = mapped_column(Date, nullable=False)
    evidence_accession: Mapped[str] = mapped_column(String(25), nullable=False)  # 8-K12B/12G3
    evidence_form: Mapped[str] = mapped_column(Text, nullable=False)
    predecessor_accession: Mapped[str | None] = mapped_column(String(25), nullable=True)
    predecessor_form: Mapped[str | None] = mapped_column(Text, nullable=True)
    match_method: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[str] = mapped_column(Text, nullable=False)
    quote: Mapped[str | None] = mapped_column(Text, nullable=True)  # the reviewed sentence
    quote_url: Mapped[str | None] = mapped_column(Text, nullable=True)  # the document it is in
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)


class CompanySegment(Base):
    """A reportable segment's figure for one fiscal year, as an annual report tags it (launch plan
    E-4), from the SEC's Financial Statement and Notes data sets (companyfacts drops dimensional
    facts). `kind` is business (the segment axis), geographic or product. `status` is ok when the
    segments add up to the consolidated figure within 1% or the filing tags a reconciling item,
    else unreconciled."""

    __tablename__ = "company_segments"
    __table_args__ = (Index("ix_company_segments_cik_filed", "cik", "filed_date"),)

    accession_number: Mapped[str] = mapped_column(String(25), primary_key=True)
    kind: Mapped[str] = mapped_column(Text, primary_key=True)
    member: Mapped[str] = mapped_column(Text, primary_key=True)  # axis=member, the stable key
    metric: Mapped[str] = mapped_column(Text, primary_key=True)
    period_end: Mapped[date] = mapped_column(Date, primary_key=True)
    cik: Mapped[str] = mapped_column(String(10), nullable=False)
    form_type: Mapped[str] = mapped_column(Text, nullable=False)
    fiscal_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    filed_date: Mapped[date] = mapped_column(Date, nullable=False)
    label: Mapped[str] = mapped_column(Text, nullable=False)
    # E-4b: "filing_label" (the filing's own label linkbase) or "member_name" (made from it)
    label_source: Mapped[str] = mapped_column(Text, nullable=False, default="member_name")
    role: Mapped[str] = mapped_column(Text, nullable=False)  # segment | reconciling | consolidated
    tag: Mapped[str] = mapped_column(Text, nullable=False)
    unit: Mapped[str] = mapped_column(Text, nullable=False)
    value: Mapped[Decimal] = mapped_column(Numeric(24, 2), nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)  # ok | unreconciled
    source: Mapped[str] = mapped_column(Text, nullable=False)


class IssuerCusip(Base):
    """Internal only (launch plan E-1): which company a CUSIP belongs to, to join Form 13F
    positions to companies. A CUSIP never appears in a response (owner rule).

    method: schedule_13dg (the issuer's CIK and CUSIP on a structured Schedule 13D or 13G),
    isin (a US or CA ISIN of a listing linked to the CIK), issuer_prefix (another share class
    with a mapped CUSIP's 6-character issuer number, as titled on Forms 13F)."""

    __tablename__ = "issuer_cusips"
    __table_args__ = (Index("ix_issuer_cusips_cik", "cik"),)

    cusip: Mapped[str] = mapped_column(String(9), primary_key=True)
    cik: Mapped[str] = mapped_column(String(10), nullable=False)
    class_title: Mapped[str | None] = mapped_column(Text, nullable=True)
    method: Mapped[str] = mapped_column(Text, nullable=False)
    accession_number: Mapped[str | None] = mapped_column(String(25), nullable=True)
    filing_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)


class Filing13F(Base):
    """One Form 13F filing by an institutional investment manager (E-1), from the SEC's Form
    13F data sets or EDGAR. The manager's address is not stored."""

    __tablename__ = "filings_13f"
    __table_args__ = (Index("ix_filings_13f_filer_period", "filer_cik", "report_period"),
                      Index("ix_filings_13f_period", "report_period"))  # fmt: skip

    accession_number: Mapped[str] = mapped_column(String(25), primary_key=True)
    filer_cik: Mapped[str] = mapped_column(String(10), nullable=False)
    filer_name: Mapped[str] = mapped_column(Text, nullable=False)  # as filed on the cover page
    report_period: Mapped[date] = mapped_column(Date, nullable=False)
    filing_date: Mapped[date] = mapped_column(Date, nullable=False)
    form_type: Mapped[str] = mapped_column(Text, nullable=False)  # 13F-HR, 13F-HR/A, 13F-NT
    amendment_type: Mapped[str | None] = mapped_column(Text, nullable=True)  # RESTATEMENT|NEW..
    report_type: Mapped[str | None] = mapped_column(Text, nullable=True)
    entry_total: Mapped[int | None] = mapped_column(Integer, nullable=True)
    value_total_usd: Mapped[Decimal | None] = mapped_column(Numeric(24, 2), nullable=True)
    confidential_omitted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    source: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)


class Holding13F(Base):
    """A manager's position in one security on one 13F filing, summed over the filing's rows
    (investment discretion, other managers). Shares only (SH), no options. Values in dollars:
    filings before 2023-01-03 reported thousands and are multiplied by 1,000."""

    __tablename__ = "holdings_13f"
    __table_args__ = (Index("ix_holdings_13f_cusip_period", "cusip", "report_period"),)

    accession_number: Mapped[str] = mapped_column(String(25), primary_key=True)
    cusip: Mapped[str] = mapped_column(String(9), primary_key=True)  # internal only
    filer_cik: Mapped[str] = mapped_column(String(10), nullable=False)
    report_period: Mapped[date] = mapped_column(Date, nullable=False)
    filing_date: Mapped[date] = mapped_column(Date, nullable=False)
    title_of_class: Mapped[str | None] = mapped_column(Text, nullable=True)
    shares: Mapped[Decimal] = mapped_column(Numeric(24, 2), nullable=False)
    value_usd: Mapped[Decimal] = mapped_column(Numeric(24, 2), nullable=False)


class ThirteenFIssuerName(Base):
    """Q-02: the issuer name most managers gave a security on their Forms 13F for a quarter, so
    a position not matched to a company here can be shown by name. The CUSIP stays internal."""

    __tablename__ = "thirteenf_issuer_names"

    cusip: Mapped[str] = mapped_column(String(9), primary_key=True)
    report_period: Mapped[date] = mapped_column(Date, primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    managers: Mapped[int] = mapped_column(Integer, nullable=False)  # filings that list it
    share: Mapped[float] = mapped_column(Float, nullable=False)  # of those giving this name


class ThirteenFReportedBy(Base):
    """Q-02: the managers a 13F names as reporting for it (its cover page's other managers), so
    a manager that files only a 13F notice (Vanguard Group since 2026) points to who reports
    its holdings. A CIK is kept when the filing gives one."""

    __tablename__ = "thirteenf_reported_by"

    accession_number: Mapped[str] = mapped_column(String(25), primary_key=True)
    seq: Mapped[int] = mapped_column(Integer, primary_key=True)
    cik: Mapped[str | None] = mapped_column(String(10), nullable=True)
    file_number: Mapped[str | None] = mapped_column(Text, nullable=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)


class ThirteenFSecurityStat(Base):
    """Q-02: one security's quarter across every manager's Form 13F after amendments: holders,
    total shares and value, and the median implied price (value over shares) that the
    thousands-after-2023 check compares filings with. The CUSIP stays internal."""

    __tablename__ = "thirteenf_security_stats"

    cusip: Mapped[str] = mapped_column(String(9), primary_key=True)
    report_period: Mapped[date] = mapped_column(Date, primary_key=True)
    holders: Mapped[int] = mapped_column(Integer, nullable=False)
    shares: Mapped[float] = mapped_column(Float, nullable=False)
    value_usd: Mapped[float] = mapped_column(Float, nullable=False)
    median_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    title: Mapped[str | None] = mapped_column(Text, nullable=True)  # most managers' class title


class ThirteenFFilingScale(Base):
    """Q-02: a 13F filing whose implied prices are about 1/1,000 of other managers' for the same
    securities (still reporting thousands after 2023): values kept, flagged, left out of totals."""

    __tablename__ = "thirteenf_filing_scale"

    accession_number: Mapped[str] = mapped_column(String(25), primary_key=True)
    report_period: Mapped[date] = mapped_column(Date, nullable=False)
    price_ratio: Mapped[float | None] = mapped_column(Float, nullable=True)  # median of positions
    suspect: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class ThirteenFActivity(Base):
    """Q-02: most bought and sold by funds: per company and share class, managers that opened,
    added, reduced or exited against the quarter before (shares, split-adjusted for reviewed
    splits; a possible unreviewed split is marked and not ranked)."""

    __tablename__ = "thirteenf_activity"

    report_period: Mapped[date] = mapped_column(Date, primary_key=True)
    issuer_cik: Mapped[str] = mapped_column(String(10), primary_key=True)
    class_label: Mapped[str] = mapped_column(Text, primary_key=True)
    previous_period: Mapped[date] = mapped_column(Date, nullable=False)
    managers_new: Mapped[int] = mapped_column(Integer, nullable=False)
    managers_added: Mapped[int] = mapped_column(Integer, nullable=False)
    managers_reduced: Mapped[int] = mapped_column(Integer, nullable=False)
    managers_exited: Mapped[int] = mapped_column(Integer, nullable=False)
    net_managers: Mapped[int] = mapped_column(Integer, nullable=False)
    holders: Mapped[int] = mapped_column(Integer, nullable=False)
    holders_previous: Mapped[int] = mapped_column(Integer, nullable=False)
    shares: Mapped[float] = mapped_column(Float, nullable=False)
    shares_previous: Mapped[float] = mapped_column(Float, nullable=False)
    split: Mapped[str | None] = mapped_column(Text, nullable=True)  # a reviewed split, "10:1"
    possible_split: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class CompanyLei(Base):
    """An SEC filer's LEI (launch plan K-01), with how it was matched and how sure we are."""

    __tablename__ = "company_lei"
    __table_args__ = (Index("ix_company_lei_lei", "lei"),)

    cik: Mapped[str] = mapped_column(String(10), primary_key=True)
    lei: Mapped[str] = mapped_column(String(20), nullable=False)
    match_method: Mapped[str] = mapped_column(Text, nullable=False)  # sec | name_jurisdiction | ...
    confidence: Mapped[str] = mapped_column(Text, nullable=False)  # high | medium
    evidence: Mapped[str] = mapped_column(Text, nullable=False)
    matched_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)


class FxRate(Base):
    """A Federal Reserve H.10 daily rate as published (public domain): some series are US
    dollars per unit (EUR, GBP, AUD, NZD), the rest units per dollar. Used only for USD-equivalent
    size cohorts; never shown as a company's figure."""

    __tablename__ = "fx_rates"

    currency: Mapped[str] = mapped_column(String(3), primary_key=True)
    rate_date: Mapped[date] = mapped_column(Date, primary_key=True)
    value: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    usd_per_unit: Mapped[bool] = mapped_column(Boolean, nullable=False)
    series_id: Mapped[str] = mapped_column(Text, nullable=False)


class FilingStatementTag(Base):
    """A revenue tag a filing places on its income statement, with the filing's own label
    (Notes data sets pre.tsv, stmt=IS, not parenthetical). Mapping 1.5.0 reads it to settle
    revenue tags that disagree within a filing, and to admit an IFRS bank's total income line."""

    __tablename__ = "filing_statement_tags"
    __table_args__ = (Index("ix_filing_statement_tags_cik", "cik"),)

    accession_number: Mapped[str] = mapped_column(String(25), primary_key=True)
    tag: Mapped[str] = mapped_column(Text, primary_key=True)
    cik: Mapped[str] = mapped_column(String(10), nullable=False)
    label: Mapped[str] = mapped_column(Text, nullable=False)
    line: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source: Mapped[str] = mapped_column(Text, nullable=False)


class GleifEntity(Base):
    """A legal entity from the GLEIF golden copy (CC0) whose exact legal name matches an SEC
    filer's (launch plan K-01b); only those are kept, not the 3.5 million records."""

    __tablename__ = "gleif_entities"
    __table_args__ = (Index("ix_gleif_entities_key", "name_key"),)

    lei: Mapped[str] = mapped_column(String(20), primary_key=True)
    legal_name: Mapped[str] = mapped_column(Text, nullable=False)
    name_key: Mapped[str] = mapped_column(Text, nullable=False)
    # normalised keys of the legal, other and transliterated names, "|"-joined (K-01c)
    norm_keys: Mapped[str | None] = mapped_column(Text, nullable=True)
    jurisdiction: Mapped[str | None] = mapped_column(Text, nullable=True)
    entity_status: Mapped[str | None] = mapped_column(Text, nullable=True)
    registration_status: Mapped[str | None] = mapped_column(Text, nullable=True)
    # K-01d: address evidence (a US state that differs between the SEC and GLEIF)
    hq_city: Mapped[str | None] = mapped_column(Text, nullable=True)
    hq_region: Mapped[str | None] = mapped_column(Text, nullable=True)
    legal_city: Mapped[str | None] = mapped_column(Text, nullable=True)
    loaded_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)


class LeiOverride(Base):
    """A hand-checked CIK to LEI link, or (lei null) a confirmed "no LEI": always wins."""

    __tablename__ = "lei_overrides"

    cik: Mapped[str] = mapped_column(String(10), primary_key=True)
    lei: Mapped[str | None] = mapped_column(String(20), nullable=True)
    note: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)


class DatedEvent(Base):
    """An event that happens on a date rather than in a filing, such as an IPO lock-up ending
    (launch plan F-02): derived from a filing, emitted on the day."""

    __tablename__ = "dated_events"
    __table_args__ = (
        UniqueConstraint("event_type", "cik", "accession_number", name="uq_dated_events"),
        Index("ix_dated_events_date", "event_date"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    cik: Mapped[str] = mapped_column(String(10), nullable=False)
    event_type: Mapped[str] = mapped_column(Text, nullable=False)
    event_date: Mapped[date] = mapped_column(Date, nullable=False)
    accession_number: Mapped[str] = mapped_column(String(25), nullable=False)  # the source filing
    detail: Mapped[str] = mapped_column(Text, nullable=False)  # JSON
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    stream_status: Mapped[str] = mapped_column(Text, nullable=False, default="skipped")
    stream_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)


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
    # paused (A-01): still the customer's watch and counted, but nothing is sent or queued
    paused: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
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
    insider_activity_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("insider_activity.id"), nullable=True
    )
    dated_event_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("dated_events.id"), nullable=True
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
    # D-04: the currency latest_revenue, latest_annual and revenue_history are in
    reporting_currency: Mapped[str | None] = mapped_column(Text, nullable=True)
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
    currency: Mapped[str | None] = mapped_column(Text, nullable=True)  # D-04: as reported


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
        # Q-03: the cross-company screener reads open-market lines by date
        Index(
            "ix_insider_transactions_open_market",
            "trans_date",
            postgresql_where=text("trans_code IN ('P', 'S') AND NOT is_derivative"),
            sqlite_where=text("trans_code IN ('P', 'S') AND NOT is_derivative"),
        ),
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


class Schedule13DPurpose(Base):
    """Q-07: Item 4 (Purpose of Transaction) of a structured Schedule 13D or 13D/A, as filed
    (whitespace collapsed); null when the amendment leaves Item 4 out."""

    __tablename__ = "schedule_13d_purposes"
    __table_args__ = (Index("ix_schedule_13d_purposes_subject", "subject_cik"),)

    accession_number: Mapped[str] = mapped_column(String(25), primary_key=True)
    subject_cik: Mapped[str] = mapped_column(String(10), nullable=False)
    purpose: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    # the class of securities (securitiesClassTitle) and "Amendment No." as filed
    class_title: Mapped[str | None] = mapped_column(Text, nullable=True)
    amendment_number: Mapped[int | None] = mapped_column(Integer, nullable=True)


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


class Watchlist(Base):
    """X-07: a named list of companies with chosen columns, stored per API key."""

    __tablename__ = "watchlists"
    __table_args__ = (Index("ix_watchlists_api_key_id", "api_key_id"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    api_key_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("api_keys.id"), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    columns: Mapped[str] = mapped_column(Text, nullable=False)  # JSON list
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)


class WatchlistCompany(Base):
    __tablename__ = "watchlist_companies"

    watchlist_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("watchlists.id", ondelete="CASCADE"), primary_key=True
    )
    cik: Mapped[str] = mapped_column(String(10), primary_key=True)
    position: Mapped[int] = mapped_column(Integer, nullable=False)


class TradingPlan(Base):
    """A trading arrangement adopted or terminated by a director or officer, as tagged under
    Item 408(a) in a 10-Q or 10-K (D-11, docs/contracts/insider-plans.md). One row per person,
    arrangement and action; values as tagged, a date that cannot be read stays as text."""

    __tablename__ = "trading_plans"
    __table_args__ = (
        UniqueConstraint("accession_number", "member", "action", name="uq_trading_plans_row"),
        Index("ix_trading_plans_cik_filed", "cik", "filing_date"),
    )

    id: Mapped[int] = mapped_column(BigSerial, primary_key=True, autoincrement=True)
    cik: Mapped[str] = mapped_column(String(10), nullable=False)
    accession_number: Mapped[str] = mapped_column(String(25), nullable=False)
    form_type: Mapped[str] = mapped_column(Text, nullable=False)
    filing_date: Mapped[date] = mapped_column(Date, nullable=False)
    period: Mapped[date | None] = mapped_column(Date, nullable=True)
    member: Mapped[str] = mapped_column(Text, nullable=False)  # the tagged dimension members
    person_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    action: Mapped[str] = mapped_column(Text, nullable=False)  # adopted, terminated
    plan_type: Mapped[str | None] = mapped_column(Text, nullable=True)
    plan_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    plan_date_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    # on a termination: the plan's adoption date when the filing gives it (an earlier period)
    original_adoption_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    duration_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    expiration_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    shares: Mapped[Decimal | None] = mapped_column(Numeric(24, 4), nullable=True)
    source: Mapped[str] = mapped_column(Text, nullable=False)


class ProxyPayFact(Base):
    """One pay-versus-performance value (Item 402(v)) as tagged in a proxy (D-10,
    docs/contracts/executive-pay.md): a field for one fiscal year, per PEO when the proxy tags
    each one. Long form; the endpoint assembles the table."""

    __tablename__ = "proxy_pay_facts"
    __table_args__ = (
        Index("ix_proxy_pay_facts_cik_filed", "cik", "filing_date"),
        Index("ix_proxy_pay_facts_accession", "accession_number"),
    )

    id: Mapped[int] = mapped_column(BigSerial, primary_key=True, autoincrement=True)
    cik: Mapped[str] = mapped_column(String(10), nullable=False)
    accession_number: Mapped[str] = mapped_column(String(25), nullable=False)
    form_type: Mapped[str] = mapped_column(Text, nullable=False)
    filing_date: Mapped[date] = mapped_column(Date, nullable=False)
    fiscal_year_end: Mapped[date | None] = mapped_column(Date, nullable=True)
    field: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str | None] = mapped_column(Text, nullable=True)  # Peo, NonPeoNeo
    member: Mapped[str | None] = mapped_column(Text, nullable=True)  # the Individual member
    dims: Mapped[str | None] = mapped_column(Text, nullable=True)
    value_num: Mapped[Decimal | None] = mapped_column(Numeric(38, 6), nullable=True)
    value_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    unit: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[str] = mapped_column(Text, nullable=False)


class Form144Notice(Base):
    """A Form 144 notice of proposed sale (D-12, docs/contracts/insider-plans.md), from the
    notice's structured XML (filed since April 2023). Values as given in the notice; the Form 4
    that follows is joined at read time."""

    __tablename__ = "form144_notices"
    __table_args__ = (Index("ix_form144_notices_issuer_filed", "issuer_cik", "filing_date"),)

    accession_number: Mapped[str] = mapped_column(String(25), primary_key=True)
    issuer_cik: Mapped[str] = mapped_column(String(10), nullable=False)
    form_type: Mapped[str] = mapped_column(Text, nullable=False)
    filing_date: Mapped[date] = mapped_column(Date, nullable=False)
    person_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    person_cik: Mapped[str | None] = mapped_column(String(10), nullable=True)
    relationships: Mapped[str] = mapped_column(Text, nullable=False)  # JSON list
    security_class: Mapped[str | None] = mapped_column(Text, nullable=True)
    shares: Mapped[Decimal | None] = mapped_column(Numeric(24, 4), nullable=True)
    aggregate_market_value: Mapped[Decimal | None] = mapped_column(Numeric(24, 2), nullable=True)
    shares_outstanding: Mapped[Decimal | None] = mapped_column(Numeric(24, 4), nullable=True)
    approx_sale_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    exchange: Mapped[str | None] = mapped_column(Text, nullable=True)
    broker: Mapped[str | None] = mapped_column(Text, nullable=True)
    acquired: Mapped[str] = mapped_column(Text, nullable=False)  # JSON list, at most 20
    acquired_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    plan_adoption_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    notice_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    source_url: Mapped[str] = mapped_column(Text, nullable=False)


class CommentLetter(Base):
    """An SEC comment letter (UPLOAD) or a company's response (CORRESP), read once for its file
    number, subject, topics and whether it closes the review (D-13,
    docs/contracts/comment-letters.md). The text is kept for tagging only; responses quote
    short snippets with the Archives link, never the text whole."""

    __tablename__ = "comment_letters"
    __table_args__ = (Index("ix_comment_letters_cik_filed", "cik", "filing_date"),)

    accession_number: Mapped[str] = mapped_column(String(25), primary_key=True)
    cik: Mapped[str] = mapped_column(String(10), nullable=False)
    form_type: Mapped[str] = mapped_column(Text, nullable=False)  # UPLOAD, CORRESP
    filing_date: Mapped[date] = mapped_column(Date, nullable=False)
    file_number: Mapped[str | None] = mapped_column(Text, nullable=True)
    subject: Mapped[str | None] = mapped_column(Text, nullable=True)
    kind: Mapped[str] = mapped_column(Text, nullable=False)  # letter, acceleration_request
    readable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    closes_review: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    topics: Mapped[str] = mapped_column(Text, nullable=False, default="[]")  # JSON list
    text: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    reader_version: Mapped[str] = mapped_column(Text, nullable=False)


class GleifRelationship(Base):
    """A GLEIF Level 2 accounting-consolidation relationship (D-14): the child's direct or
    ultimate parent, as the child reports it (golden copy, CC0). Kept where a filer's LEI is on
    either side."""

    __tablename__ = "gleif_relationships"
    __table_args__ = (Index("ix_gleif_relationships_parent", "parent_lei"),)

    child_lei: Mapped[str] = mapped_column(String(20), primary_key=True)
    kind: Mapped[str] = mapped_column(Text, primary_key=True)  # direct, ultimate
    parent_lei: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str | None] = mapped_column(Text, nullable=True)  # ACTIVE, INACTIVE
    period_start: Mapped[date | None] = mapped_column(Date, nullable=True)


class GleifException(Base):
    """A GLEIF Level 2 reporting exception: why an entity reports no direct or ultimate parent
    (NATURAL_PERSONS, NON_CONSOLIDATING, NO_KNOWN_PERSON, ...), as GLEIF gives it."""

    __tablename__ = "gleif_exceptions"

    lei: Mapped[str] = mapped_column(String(20), primary_key=True)
    kind: Mapped[str] = mapped_column(Text, primary_key=True)  # direct, ultimate
    reason: Mapped[str] = mapped_column(Text, nullable=False)


class GleifName(Base):
    """Name, jurisdiction and status of an LEI that a Level 2 relationship or an exhibit 21 match
    refers to (kept apart from gleif_entities, which drives filer matching)."""

    __tablename__ = "gleif_names"

    lei: Mapped[str] = mapped_column(String(20), primary_key=True)
    legal_name: Mapped[str] = mapped_column(Text, nullable=False)
    jurisdiction: Mapped[str | None] = mapped_column(Text, nullable=True)
    entity_status: Mapped[str | None] = mapped_column(Text, nullable=True)


class SubsidiaryLei(Base):
    """An exhibit 21 subsidiary linked to an LEI: exactly one GLEIF entity has the same
    normalised legal name and an agreeing jurisdiction (a doubtful link is worse than none)."""

    __tablename__ = "subsidiary_leis"

    subsidiary_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    lei: Mapped[str] = mapped_column(String(20), nullable=False)


class FormDFiling(Base):
    """A Form D or D/A notice of an exempt offering (D-15, docs/contracts/private-raises.md),
    from the SEC's structured Form D data sets: the primary issuer, the offering and up to ten
    related persons as filed. Amendments share the original's file number; is_latest marks the
    newest filing of each offering. Self-reported by the issuer; amounts as filed."""

    __tablename__ = "form_d_filings"
    __table_args__ = (
        Index("ix_form_d_filings_cik", "cik"),
        Index("ix_form_d_filings_file", "file_number"),
        Index("ix_form_d_filings_latest", "is_latest", "filing_date"),
    )

    accession_number: Mapped[str] = mapped_column(String(25), primary_key=True)
    file_number: Mapped[str | None] = mapped_column(Text, nullable=True)
    form_type: Mapped[str] = mapped_column(Text, nullable=False)  # D, D/A
    filing_date: Mapped[date] = mapped_column(Date, nullable=False)
    cik: Mapped[str] = mapped_column(String(10), nullable=False)
    issuer_name: Mapped[str] = mapped_column(Text, nullable=False)
    state: Mapped[str | None] = mapped_column(Text, nullable=True)
    jurisdiction: Mapped[str | None] = mapped_column(Text, nullable=True)
    entity_type: Mapped[str | None] = mapped_column(Text, nullable=True)
    year_of_incorporation: Mapped[str | None] = mapped_column(Text, nullable=True)
    industry_group: Mapped[str | None] = mapped_column(Text, nullable=True)
    total_offering_amount: Mapped[Decimal | None] = mapped_column(Numeric(24, 2), nullable=True)
    indefinite: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    total_amount_sold: Mapped[Decimal | None] = mapped_column(Numeric(24, 2), nullable=True)
    total_remaining: Mapped[Decimal | None] = mapped_column(Numeric(24, 2), nullable=True)
    investors_total: Mapped[int | None] = mapped_column(Integer, nullable=True)
    investors_non_accredited: Mapped[int | None] = mapped_column(Integer, nullable=True)
    first_sale_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    first_sale_yet_to_occur: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    exemptions: Mapped[str | None] = mapped_column(Text, nullable=True)  # codes as filed, comma
    minimum_investment: Mapped[Decimal | None] = mapped_column(Numeric(24, 2), nullable=True)
    sales_commissions: Mapped[Decimal | None] = mapped_column(Numeric(24, 2), nullable=True)
    finders_fees: Mapped[Decimal | None] = mapped_column(Numeric(24, 2), nullable=True)
    related_persons: Mapped[str] = mapped_column(Text, nullable=False, default="[]")  # JSON
    related_persons_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_latest: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # D-15b: ok, or suspect_amount (an implausible self-reported amount, values kept as filed)
    quality_status: Mapped[str] = mapped_column(Text, nullable=False, default="ok")
    source: Mapped[str] = mapped_column(Text, nullable=False)
