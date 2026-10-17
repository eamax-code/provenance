from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.common import ORMModel, PageMeta


class WatchCreate(BaseModel):
    cik: str = Field(min_length=1, max_length=13)
    destination_type: Literal["webhook", "email"]
    destination: str = Field(min_length=3, max_length=2048)


class WatchOut(ORMModel):
    id: UUID
    cik: str
    destination_type: str
    destination: str
    is_active: bool
    created_at: datetime
    deactivated_at: datetime | None
    last_delivered_at: datetime | None


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
