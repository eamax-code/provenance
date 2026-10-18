"""Timestamp helpers shared across services and schemas."""

from __future__ import annotations

from datetime import UTC, datetime


def iso_z(dt: datetime | None) -> str | None:
    """ISO 8601 in UTC with a Z suffix, or None."""
    if dt is None:
        return None
    return dt.astimezone(UTC).isoformat().replace("+00:00", "Z")
