from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, Field, computed_field, field_serializer, field_validator

from app.schemas.common import ORMModel, PageMeta
from app.services.sec_client import company_filings_url


class CompanyOut(ORMModel):
    cik: str = Field(description="10-digit zero-padded SEC Central Index Key")
    legal_name: str
    ticker: str | None
    exchange: str | None
    sic_code: str | None = None
    sic_description: str | None = None
    entity_type: str | None = None
    state_of_incorporation: str | None = None
    fiscal_year_end: str | None = Field(default=None, description="MMDD as reported by SEC")
    last_processed_at: datetime | None
    quality_status: str
    ingestion_status: str = Field(
        default="complete", description="complete | pending | processing | failed"
    )
    match_type: str | None = Field(
        default=None,
        description="Search only: cik | ticker | name_exact (the name, ignoring words such as Inc. "
        "and Corp.) | name_prefix | name_contains | "
        "former_name (a name the company used before; see matched_name) | name_fuzzy (a "
        "spelling one or two letters off; offered only when nothing else matches)",
    )
    matched_name: str | None = Field(
        default=None, description="Search only: the former name that matched, for former_name"
    )

    @computed_field(description="The company's filing list on SEC EDGAR")
    @property
    def filings_url(self) -> str:
        return company_filings_url(self.cik)


class CompanyList(BaseModel):
    data: list[CompanyOut]
    meta: PageMeta


class CompanyProfile(CompanyOut):
    filings_count: int = 0
    facts_count: int = 0
    last_fetch_error: str | None = None
    last_fetch_error_at: datetime | None = None


class FilingOut(ORMModel):
    cik: str
    accession_number: str
    form_type: str
    filing_date: date | None
    report_date: date | None = None
    accepted_at: datetime | None = Field(
        description="SEC EDGAR acceptance timestamp when provided by the source; otherwise null"
    )
    source_published_at: datetime | None = Field(
        description="Always null for now: the SEC source does not expose a dissemination timestamp"
    )
    primary_document: str | None = None
    items: list[str] = Field(
        default_factory=list,
        description="8-K item codes listed on the filing, e.g. 5.02 (officer changes)",
    )
    source_url: str = Field(description="The filing's index page on SEC EDGAR")
    processed_at: datetime | None
    quality_status: str

    @field_validator("items", mode="before")
    @classmethod
    def _split_items(cls, value):
        if value is None:
            return []
        if isinstance(value, str):
            return [i for i in value.split(",") if i]
        return value


class FilingList(BaseModel):
    data: list[FilingOut]
    meta: PageMeta


class FactOut(ORMModel):
    cik: str
    metric: str
    value: Decimal | None
    unit: str
    currency: str | None
    period_start: date | None
    period_end: date
    period_type: str
    period_class: str = Field(
        description="annual | quarterly | ytd | other (derived from duration)"
    )
    fiscal_year: int | None
    fiscal_period: str | None = Field(description="SEC fp label of the filing; not a duration")
    form_type: str | None
    filed_date: date | None
    accession_number: str | None
    source_tag: str
    source_taxonomy: str
    source_url: str
    mapping_version: str
    quality_status: str
    derived: bool
    derivation: dict | None = None
    revision_count: int = Field(
        default=1, description="Number of stored observations for the same metric/unit/period"
    )
    is_latest_revision: bool = True
    processed_at: datetime

    @field_serializer("value")
    def _serialize_value(self, value: Decimal | None):
        """Emit JSON numbers: an exact integer when integral, otherwise a float."""
        if value is None:
            return None
        normalized = value.normalize()
        if normalized == normalized.to_integral_value():
            return int(normalized)
        return float(normalized)


class FactList(BaseModel):
    data: list[FactOut]
    meta: PageMeta
    mapping_version: str
    as_of: date | None = Field(
        None, description="Point-in-time date the response was restricted to, if any"
    )
    notes: list[str] = []


class LatestFilingFreshness(BaseModel):
    accession_number: str
    form_type: str
    filing_date: date | None
    accepted_at: datetime | None
    source_published_at: datetime | None
    processed_at: datetime | None
    publication_to_detection_seconds: float | None
    acceptance_to_detection_seconds: float | None
    source_date_age_seconds: int | None
    processing_seconds: float | None
    quality_status: str


class IngestionFreshness(BaseModel):
    last_run_started_at: datetime | None
    last_run_finished_at: datetime | None
    last_run_status: str | None
    last_run_error_count: int | None
    poll_interval_seconds: int
    stale_after_seconds: int


class FreshnessOut(BaseModel):
    cik: str
    last_successful_fetch_at: datetime | None
    last_successful_fetch_age_seconds: int | None
    last_fetch_error_at: datetime | None
    last_fetch_error: str | None
    latest_filing: LatestFilingFreshness | None
    ingestion: IngestionFreshness
    status: str
    notes: list[str]
