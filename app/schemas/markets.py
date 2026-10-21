from __future__ import annotations

import json
from datetime import date, datetime

from pydantic import BaseModel, Field, field_validator

from app.schemas.common import ORMModel, PageMeta


class MarketOut(ORMModel):
    mic: str
    operating_mic: str | None
    name: str
    country: str
    region: str
    source: str
    source_url: str
    is_active: bool
    instruments_listed: int = 0
    instruments_delisted: int = 0
    last_seen_at: datetime | None = None


class MarketList(BaseModel):
    data: list[MarketOut]
    notes: list[str]


class IssuerOut(ORMModel):
    lei: str | None
    legal_name: str
    country: str | None
    jurisdiction: str | None
    registration_status: str | None
    source: str
    source_url: str | None
    first_detected_at: datetime
    updated_at: datetime


class InstrumentOut(ORMModel):
    isin: str | None
    listing_key: str
    mic: str
    issuer_name: str
    issuer_lei: str | None
    symbol: str | None
    short_name: str | None
    cfi_code: str | None
    instrument_type: str
    currency: str | None
    admission_requested_date: date | None
    admission_approved_date: date | None
    first_trade_date: date | None
    termination_date: date | None
    status: str
    source: str
    source_url: str
    source_published_at: datetime | None
    first_detected_at: datetime
    last_seen_at: datetime
    processed_at: datetime
    quality_status: str


class InstrumentList(BaseModel):
    data: list[InstrumentOut]
    meta: PageMeta


class InstrumentDetail(BaseModel):
    isin: str
    listings: list[InstrumentOut]
    issuer: IssuerOut | None
    notes: list[str]


class ListingEventOut(ORMModel):
    isin: str | None
    listing_key: str
    symbol: str | None
    mic: str
    issuer_name: str
    event_type: str = Field(
        description="new_listing | ipo | delisting | modified | suspended | reinstated"
    )
    event_date: date | None
    source: str
    source_url: str
    details: dict | None = None
    detected_at: datetime
    quality_status: str

    @field_validator("details", mode="before")
    @classmethod
    def _parse_details(cls, value):
        if isinstance(value, str):
            try:
                return json.loads(value)
            except ValueError:
                return None
        return value


class ListingEventList(BaseModel):
    data: list[ListingEventOut]
    meta: PageMeta
    notes: list[str]


class IssuerDetail(BaseModel):
    issuer: IssuerOut
    listings: list[InstrumentOut]
