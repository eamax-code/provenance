from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from app.schemas.common import ORMModel, PageMeta


class WatchCreate(BaseModel):
    cik: str = Field(min_length=1, max_length=13)
    destination_type: Literal["webhook", "email"]
    destination: str = Field(min_length=3, max_length=2048)
    event_types: list[str] | None = Field(
        default=None,
        max_length=20,
        description="Only filings that carry one of these event types, e.g. "
        '["sec.restatement", "sec.bankruptcy"]; omit for every new filing',
    )


class WatchPatch(BaseModel):
    is_active: bool = Field(
        description="false pauses the watch (nothing is sent or queued while paused; it still "
        "counts toward the plan); true resumes it"
    )


class WatchOut(ORMModel):
    id: UUID
    cik: str
    destination_type: str
    destination: str
    is_active: bool
    paused: bool = False
    created_at: datetime
    deactivated_at: datetime | None
    last_delivered_at: datetime | None
    event_types: list[str] | None = None

    @field_validator("event_types", mode="before")
    @classmethod
    def _split_types(cls, v):
        return [t for t in v.split(",") if t] if isinstance(v, str) else v


class WatchCreated(WatchOut):
    webhook_secret: str | None = Field(
        default=None, description="Webhook watches only. Shown exactly once."
    )
    signature_scheme: str = "HMAC-SHA256 over '<timestamp>.<body>' in X-Signature (v1=hex)"


class WatchList(BaseModel):
    data: list[WatchOut]
    meta: PageMeta


class DeliveryOut(ORMModel):
    id: UUID
    watch_id: UUID
    filing_id: UUID
    event_id: str
    status: str
    attempt_count: int
    last_status_code: int | None
    last_error_redacted: str | None
    next_attempt_at: datetime | None
    created_at: datetime
    delivered_at: datetime | None


class DeliveryList(BaseModel):
    data: list[DeliveryOut]
    meta: PageMeta


DEFAULT_LISTING_EVENTS = ["new_listing", "delisting", "suspended"]


class ListingWatchCreate(BaseModel):
    scope_type: Literal["mic", "country", "region"] = Field(
        description="Watch one venue (MIC), every covered venue in a country, or a region"
    )
    scope_value: str = Field(
        min_length=2, max_length=10, description="XPAR, FR, or canada | europe | uk"
    )
    event_types: list[str] = Field(
        default_factory=lambda: list(DEFAULT_LISTING_EVENTS),
        description="new_listing, ipo, delisting, suspended, reinstated, modified",
    )
    destination_type: Literal["webhook", "email"]
    destination: str = Field(min_length=3, max_length=2048)


class ListingWatchOut(ORMModel):
    id: UUID
    scope_type: str
    scope_value: str
    event_types: list[str]
    destination_type: str
    destination: str
    is_active: bool
    paused: bool = False
    created_at: datetime
    deactivated_at: datetime | None
    last_delivered_at: datetime | None

    @field_validator("event_types", mode="before")
    @classmethod
    def _split(cls, value):
        return value.split(",") if isinstance(value, str) else value


class ListingWatchCreated(ListingWatchOut):
    webhook_secret: str | None = Field(
        default=None, description="Webhook watches only. Shown exactly once."
    )
    signature_scheme: str = "HMAC-SHA256 over '<timestamp>.<body>' in X-Signature (v1=hex)"


class ListingWatchList(BaseModel):
    data: list[ListingWatchOut]
    meta: PageMeta


class ListingDeliveryOut(ORMModel):
    id: UUID
    listing_watch_id: UUID
    listing_event_id: UUID
    event_id: str
    status: str
    attempt_count: int
    last_status_code: int | None
    last_error_redacted: str | None
    next_attempt_at: datetime | None
    created_at: datetime
    delivered_at: datetime | None


class ListingDeliveryList(BaseModel):
    data: list[ListingDeliveryOut]
    meta: PageMeta


class TypeWatchCreate(BaseModel):
    event_types: list[str] = Field(
        min_length=1,
        max_length=20,
        description='Filing event types, e.g. ["sec.restatement", "sec.auditor_change"]',
    )
    sic_prefix: str | None = Field(
        default=None, pattern=r"^\d{1,4}$", description='Only companies whose SIC starts so: "28"'
    )
    exchange: str | None = Field(default=None, max_length=20, description='e.g. "Nasdaq", "NYSE"')
    filer_category: str | None = Field(
        default=None, max_length=60, description='e.g. "Large accelerated filer"'
    )
    ciks: list[str] | None = Field(default=None, max_length=500, description="At most 500 CIKs")
    destination: str = Field(min_length=3, max_length=2048, description="HTTPS webhook URL")


class TypeWatchOut(ORMModel):
    id: UUID
    event_types: list[str]
    sic_prefix: str | None
    exchange: str | None
    filer_category: str | None
    ciks: list[str] | None
    delivery_mode: str = Field(
        description="immediate: one webhook per filing; hourly: the hour's filings in one webhook"
    )
    destination: str
    is_active: bool
    paused: bool = False
    created_at: datetime
    deactivated_at: datetime | None
    last_delivered_at: datetime | None

    @field_validator("event_types", "ciks", mode="before")
    @classmethod
    def _split(cls, v):
        return [t for t in v.split(",") if t] if isinstance(v, str) else v


class TypeWatchCreated(TypeWatchOut):
    webhook_secret: str = Field(description="Shown exactly once.")
    signature_scheme: str = "HMAC-SHA256 over '<timestamp>.<body>' in X-Signature (v1=hex)"


class TypeWatchList(BaseModel):
    data: list[TypeWatchOut]
    meta: PageMeta


class TypeDeliveryOut(ORMModel):
    id: UUID
    type_watch_id: UUID
    filing_id: UUID | None
    insider_activity_id: UUID | None
    dated_event_id: UUID | None
    event_id: str
    status: str
    attempt_count: int
    last_status_code: int | None
    last_error_redacted: str | None
    next_attempt_at: datetime | None
    created_at: datetime
    delivered_at: datetime | None


class TypeDeliveryList(BaseModel):
    data: list[TypeDeliveryOut]
    meta: PageMeta
