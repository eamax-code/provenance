"""Institutional ownership from Form 13F (launch plan E-1)."""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.schemas.common import PageMeta


class SharesOutstanding(BaseModel):
    value: float
    unit: str | None = None
    as_of_date: str | None = None
    form_type: str | None = None
    filed_date: str | None = None
    accession_number: str | None = None
    source_url: str | None = None


class DerivedInput(BaseModel):
    name: str
    value: float
    quarter: str | None = None
    as_of_date: str | None = None
    source_url: str | None = None


class Derivation(BaseModel):
    formula: str
    inputs: list[DerivedInput]


class Flows(BaseModel):
    new: int = Field(description="Managers with a position now and none the quarter before")
    added: int
    reduced: int
    exited: int = Field(description="Managers that filed for the quarter without a position")
    not_filed: int = Field(
        0, description="Last quarter's holders that have filed no 13F for this quarter yet; "
        "holders_count_change = new - exited - not_filed",
    )


class Holder(BaseModel):
    filer_cik: str = Field(description="The manager's own CIK")
    name: str = Field(description="The manager's name as filed on the 13F cover page")
    value_usd: float = Field(description="Value at quarter end in dollars, as reported")
    shares: float | None = Field(None, description="Null when the company has several classes")
    pct_of_outstanding: float | None = None
    change: str | None = Field(None, description="new, added, reduced or unchanged")
    shares_change: float | None = None
    shares_change_pct: float | None = None
    filing_date: str
    form_type: str
    accession_number: str
    filing_url: str = Field(description="The 13F filing's index page on sec.gov")


class OwnershipOut(BaseModel):
    cik: str
    quarter: str = Field(description="Report period of the latest complete quarter")
    previous_quarter: str
    filed_through: str | None = Field(None, description="Latest 13F filing date included")
    lag_note: str
    holders_count: int
    holders_count_change: int | None = None
    value_usd: float = Field(description="Sum of the managers' reported values, in dollars")
    shares_held: float | None = None
    shares_outstanding: SharesOutstanding | None = None
    institutional_pct: float | None = Field(None, description="Derived: shares held / outstanding")
    institutional_pct_derived: Derivation | None = None
    flows: Flows
    flows_note: str | None = Field(
        None, description="Set when the quarter spans a change of share identifier"
    )
    data: list[Holder] = Field(description="Holders by value at quarter end, largest first")
    meta: PageMeta
    as_of: str | None = None
    notes: list[str]
