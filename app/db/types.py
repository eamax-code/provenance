"""Portable column types: PostgreSQL in deployment, SQLite in tests."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import BigInteger, DateTime, Integer
from sqlalchemy.types import TypeDecorator


class UTCDateTime(TypeDecorator):
    """TIMESTAMPTZ on PostgreSQL; on SQLite values are stored naive-UTC and re-attached."""

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if not isinstance(value, datetime):
            raise TypeError("UTCDateTime expects datetime values")
        if value.tzinfo is None:
            raise ValueError("naive datetime passed to UTCDateTime; use timezone-aware UTC")
        value = value.astimezone(UTC)
        if dialect.name == "sqlite":
            return value.replace(tzinfo=None)
        return value

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)


BigSerial = BigInteger().with_variant(Integer(), "sqlite")
