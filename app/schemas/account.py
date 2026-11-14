from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field

from app.schemas.common import ORMModel
from app.schemas.developer import UI_THEMES


class SignInRequest(BaseModel):
    email: EmailStr = Field(max_length=254)


class SignInSent(BaseModel):
    status: str = "sent"
    message: str


class VerifyRequest(BaseModel):
    token: str = Field(min_length=20, max_length=200)


class AccountKey(ORMModel):
    id: UUID
    key_prefix: str
    label: str | None
    plan: str
    is_active: bool
    created_at: datetime
    last_used_at: datetime | None
    revoked_at: datetime | None
    requests_this_month: int = 0


class AccountOut(BaseModel):
    email: str
    created_at: datetime
    plan: str = Field(description="The best plan among the account's active keys")
    ui_theme: str
    monthly_request_quota: int
    requests_this_month: int = Field(description="All of the account's keys, this UTC month")
    max_active_keys: int
    keys: list[AccountKey]


class AccountUpdate(BaseModel):
    ui_theme: str = Field(pattern="^(" + "|".join(UI_THEMES) + ")$")


class KeyCreate(BaseModel):
    label: str | None = Field(default=None, max_length=60)


class KeyCreated(AccountKey):
    api_key: str = Field(description="Shown exactly once. Store it securely.")
