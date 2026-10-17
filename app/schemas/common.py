from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class ErrorBody(BaseModel):
    code: str
    message: str
    request_id: str | None = None


class ErrorEnvelope(BaseModel):
    error: ErrorBody


class PageMeta(BaseModel):
    limit: int
    offset: int = 0
    has_more: bool
    next_offset: int | None = None
    total_matched: int | None = Field(default=None, description="Present when cheaply known")


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)
