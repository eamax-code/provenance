"""X-02: a whole financial statement in one call (docs/api-contracts-explorer.md)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from pydantic import BaseModel, Field


class StatementColumn(BaseModel):
    key: str
    period_label: str | None = None
    period_fiscal_year: int | None = None
    period_start: date | None = None
    period_end: date
    calendar_period: str | None = None


class StatementCell(BaseModel):
    column: str
    value: Decimal | float | None
    unit: str
    period_start: date | None = None
    period_end: date | None = None
    form_type: str | None = None
    filed_date: date | None = None
    accession_number: str | None = None
    source_url: str | None = Field(None, description="The filing on sec.gov/Archives")
    source_tag: str | None = None
    source_taxonomy: str | None = None
    mapping_version: str | None = None
    quality_status: str | None = None
    derived: bool = False
    derivation: dict | None = None
    inputs: list[dict] | None = Field(None, description="For a derived row: each input's filing")


class StatementRow(BaseModel):
    metric: str
    label: str
    unit_kind: str
    derived: bool = False
    formula: str | None = None
    cells: list[StatementCell | None]


class StatementOut(BaseModel):
    cik: str
    statement: str
    period: str
    as_of: str | None = None
    reporting_currency: str | None = None
    mapping_version: str
    columns: list[StatementColumn]
    rows: list[StatementRow]
    notes: list[str]
