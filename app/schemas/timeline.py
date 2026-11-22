"""X-05: a company's timeline (docs/api-contracts-explorer.md)."""

from __future__ import annotations

from pydantic import BaseModel, Field


class TimelineItem(BaseModel):
    id: str
    date: str = Field(description="ISO date: the filing date, or the event's own date")
    type: str = Field(description="filing, 8k_item, officer_change, auditor_change, ipo, insider "
                      "or 13f_quarter")  # fmt: skip
    event_type: str | None = Field(None, description="The canonical name, as /v1/event-types")
    title: str
    form_type: str | None = None
    accession_number: str | None = None
    filing_url: str | None = Field(
        None, description="The filing on sec.gov/Archives; null for a 13F quarter (see /ownership)"
    )
    upcoming: bool = Field(False, description="A derived future date, such as a lock-up end")
    details: dict = Field(default_factory=dict)


class TimelineMeta(BaseModel):
    limit: int
    has_more: bool
    next_cursor: str | None = None


class TimelineOut(BaseModel):
    cik: str
    as_of: str | None = None
    data: list[TimelineItem]
    meta: TimelineMeta
    notes: list[str]
