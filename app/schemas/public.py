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
        description="Effective monthly price when billed yearly"
    )
    price_display: str = Field(description='Price as shown, e.g. "$79" or "From $1,500"')
    audience: str
    use: str = Field(description="What the plan may be used for")
    commercial_use: bool = Field(description="Data may be shown to your own users")
    keys: int = Field(description="Active API keys per account")
    rate_limit_per_minute: int
    monthly_request_quota: int
    max_watches: int
    max_active_watches: int
    max_event_streams: int
    max_export_rows: int
    chat_questions_per_day: int
    max_watchlists: int = Field(description="Saved watchlists per key (X-07)")
    max_watchlist_companies: int = Field(description="Companies per watchlist")
    max_watchlist_columns: int = Field(description="Columns per watchlist")
    forecasts: bool
    support: str
    features: list[str]


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
    cover: dict | None = Field(
        default=None,
        description="Cover page: shares_outstanding and public_float (value, unit, as_of_date, "
        "form_type, filed_date, accession_number, source_url, or null), filer_category, "
        "fiscal_year_end (MMDD)",
    )
    freshness: FreshnessOut
    mapping_version: str
    notes: list[str]
    generated_at: str
