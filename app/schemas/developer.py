from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field

from app.core.config import PLAN_NAMES
from app.schemas.common import ORMModel


class ApiKeyCreate(BaseModel):
    owner_email: EmailStr
    plan: str = Field(default="free", pattern="^(" + "|".join(PLAN_NAMES) + ")$")
    label: str | None = Field(default=None, max_length=100)


class ApiKeyOut(ORMModel):
    id: UUID
    owner_email: str
    key_prefix: str
    plan: str
    label: str | None
    is_active: bool
    created_at: datetime
    last_used_at: datetime | None
    revoked_at: datetime | None


class ApiKeyCreated(ApiKeyOut):
    api_key: str = Field(description="Shown exactly once. Store it securely.")


class ApiKeyList(BaseModel):
    data: list[ApiKeyOut]


class PlanInfo(BaseModel):
    plan: str
    rate_limit_per_minute: int
    monthly_request_quota: int
    monthly_requests_used: int
    max_export_rows: int
    max_watches: int
    watched_companies_used: int
    max_active_watches: int
    active_watches_used: int


class UsageOut(BaseModel):
    from_: datetime = Field(alias="from")
    to: datetime
    total_requests: int
    successful_requests: int
    error_requests: int
    requests_by_route: dict[str, int]
    export_rows: int
    export_bytes: int
    response_bytes: int
    plan: PlanInfo

    model_config = {"populate_by_name": True}
