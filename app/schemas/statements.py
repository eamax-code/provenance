"""X-02: a whole financial statement in one call (docs/api-contracts-explorer.md)."""

from __future__ import annotations

from datetime import date

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
    value: float | None = Field(description="A JSON number (never a string)")
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
    registrant_cik: str | None = Field(None, description="Who filed it (K-05)")
    predecessor: bool = Field(False, description="Filed by a predecessor registrant")
    registrant_label: str | None = None


class StatementRow(BaseModel):
    metric: str
    label: str
    unit_kind: str
    derived: bool = False
    formula: str | None = None
    split_break: dict | None = Field(
        None,
        description="Adjacent years on different share bases (a split restated in later "
        'filings for some years only): {"between": [label, label], "ratio_hint": "4:1"}, the '
        'latest such pair; older reviewed splits under "earlier" (newest first); "split_date" '
        'from the reviewed split list or null; "restated_in" the filing behind the first '
        "newer-basis column. Values are not adjusted.",
    )
    split_adjusted: dict | None = Field(
        None,
        description="S-02: beside the as-filed cells, the same row on the post-split share "
        'basis: {"ratio": "4:1", "derived": true, "values": [...per column], "source": {the '
        'filing that shows the ratio, with its evidence}, "basis"}; older splits a filing also '
        'confirms are compounded into the values before them and listed under "earlier" ([{ratio, '
        "before, source}]). Only when a filing confirms the ratio; the as-filed cells stay the "
        "default.",
    )
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
