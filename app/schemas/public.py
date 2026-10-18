from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, Field, field_serializer

from app.schemas.companies import CompanyOut, FactOut, FilingOut, FreshnessOut


class PublicPlan(BaseModel):
    name: str
    label: str
    featured: bool
    price_usd_per_month: int | None = Field(description="Monthly price in USD; null = contact")
    annual_price_usd_per_month: int | None = Field(
        description="Effective monthly price when billed yearly (two months free)"
    )
    rate_limit_per_minute: int
    monthly_request_quota: int
    max_watches: int
    max_active_watches: int
    max_export_rows: int


class PublicPlans(BaseModel):
    data: list[PublicPlan]
    max_export_rows: int
    pricing_status: str = "pilot"
    disclaimer: str
    generated_at: str


class LatestFilingCard(BaseModel):
    form_type: str
    filing_date: str | None
    accession_number: str
    source_url: str


class LatestRevenueCard(BaseModel):
    value: Decimal | None
    unit: str
    currency: str | None
    period_start: str | None
    period_end: str
    fiscal_year: int | None
    form_type: str | None
    filed_date: str | None
    accession_number: str | None
    source_tag: str
    source_url: str
    quality_status: str

    @field_serializer("value")
    def _value(self, value: Decimal | None):
        if value is None:
            return None
        n = value.normalize()
        return int(n) if n == n.to_integral_value() else float(n)


class ShowcaseCompany(BaseModel):
    cik: str
    legal_name: str
    ticker: str | None
    exchange: str | None
    sic_description: str | None
    last_processed_at: str | None
    filings_count: int
    facts_count: int
    latest_filing: LatestFilingCard | None
    latest_annual_revenue: LatestRevenueCard | None


class ShowcaseList(BaseModel):
    data: list[ShowcaseCompany]
    meta: dict
    generated_at: str
    disclaimer: str


class PublicMetricSeries(BaseModel):
    metric: str
    label: str
    status: str = Field(description="ok | ambiguous_mapping | unavailable")
    note: str
    facts: list[FactOut]


class PublicCompanyBundle(BaseModel):
    company: CompanyOut
    filings: list[FilingOut]
    metrics: list[PublicMetricSeries]
    freshness: FreshnessOut
    mapping_version: str
    notes: list[str]
    generated_at: str
