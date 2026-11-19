from __future__ import annotations

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, Field

from app.schemas.common import PageMeta


class FilingRef(BaseModel):
    form_type: str
    accession_number: str
    filing_date: date | None
    source_url: str = Field(description="The filing on SEC EDGAR")


class GraphNode(BaseModel):
    id: str
    type: str = Field(description="company, person, entity, organization or subsidiary")
    label: str
    cik: str | None = Field(None, description="Set when the node is a company in this API")
    group: str = Field(description="center, insiders, interlocks, holders or subsidiaries")
    detail: dict[str, Any] = Field(default_factory=dict)


class GraphEdge(BaseModel):
    source: str
    target: str
    type: str = Field(
        description="officer, director, ten_percent_owner, other_insider, interlock, holder "
        "or subsidiary"
    )
    label: str
    current: bool
    since: date | None = None
    last: date | None = Field(None, description="Date of the latest filing behind the edge")
    filings: int | None = None
    percent: float | None = None
    shares: float | None = None
    evidence: FilingRef


class CompanyRef(BaseModel):
    cik: str
    name: str | None
    ticker: str | None = None


class GraphOut(BaseModel):
    company: CompanyRef
    as_of: date | None
    nodes: list[GraphNode]
    edges: list[GraphEdge]
    sources: dict[str, Any]
    coverage: dict[str, Any]
    refreshing: bool = Field(
        False, description="True when sources are being read from EDGAR; ask again shortly"
    )


class OpenMarket(BaseModel):
    bought_value: float
    sold_value: float
    buys: int
    sells: int


class InsiderOut(BaseModel):
    owner_cik: str = Field(description="The reporting owner's CIK on EDGAR")
    name: str
    name_as_filed: str
    kind: str = Field(description="person or entity")
    role: str
    is_director: bool
    is_officer: bool
    is_ten_percent_owner: bool
    officer_title: str | None
    current: bool = Field(description="Filed in the last two years (before as_of when given)")
    first_filed: date
    last_filed: date
    filings: int
    shares_held: float | None = Field(
        description="Non-derivative shares held after the latest reported transaction or holding"
    )
    open_market_12m: OpenMarket
    latest_filing: FilingRef
    company_cik: str | None = Field(None, description="Set when the owner is a company here")
    other_companies: list[dict[str, Any]] = Field(default_factory=list)


class InsiderList(BaseModel):
    data: list[InsiderOut]
    through: date | None = Field(description="Newest filing date of the loaded data sets")
    as_of: date | None


class InsiderTransactionOut(BaseModel):
    accession_number: str
    filing_date: date
    form_type: str
    owner_cik: str
    owner_name: str
    role: str
    security_title: str | None
    is_derivative: bool
    trans_date: date | None
    trans_code: str | None
    trans_code_label: str | None
    acquired_disposed: str | None
    shares: float | None
    price: float | None
    value: float | None
    shares_after: float | None
    direct_indirect: str | None
    plan_10b5_1: bool | None
    source_url: str


class InsiderTransactionList(BaseModel):
    data: list[InsiderTransactionOut]
    meta: PageMeta


class SubsidiaryOut(BaseModel):
    name: str
    jurisdiction: str | None
    jurisdiction_group: str
    new_this_year: bool
    company_cik: str | None = None


class SubsidiaryList(BaseModel):
    data: list[SubsidiaryOut]
    filing: FilingRef | None
    exhibit: str | None
    previous: dict[str, Any] | None
    added: list[str]
    removed: list[str]
    checked_at: datetime | None = None
    refreshing: bool = False


class HolderOut(BaseModel):
    name: str
    cik: str | None
    holder_type: str | None
    holder_type_label: str | None
    percent: float | None
    shares: float | None
    below_threshold: bool
    schedule: str
    event_date: date | None
    group: list[str]
    filing: FilingRef
    company_cik: str | None = None


class HolderList(BaseModel):
    data: list[HolderOut]
    as_of: date | None
    note: str
    refreshing: bool = False


class IpoOut(BaseModel):
    cik: str
    name: str
    ticker: str | None = Field(None, description="Set once the SEC lists one for the company")
    exchange: str | None = None
    kind: str = Field(description="ipo (S-1, F-1 or DRS) or spin_off (Form 10)")
    stage: str = Field(
        description="confidential, filed, amended, effective, listing, priced or withdrawn"
    )
    blank_check: bool = Field(description="A blank-check company (SPAC), SIC 6770")
    last_activity: date
    milestones: dict[str, FilingRef] = Field(
        description="The filing behind each milestone reached: the first of each, the latest "
        "amendment"
    )


class IpoList(BaseModel):
    data: list[IpoOut]
    meta: PageMeta
