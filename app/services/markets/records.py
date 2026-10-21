"""Source-agnostic listing record and event vocabulary.

Every source adapter (ESMA FIRDS, FCA FIRDS, exchange lists, ...) produces ListingRecord
objects; the ingestion layer turns them into rows and lifecycle events. Nothing here knows
about any source format.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import date, datetime

EVENT_NEW_LISTING = "new_listing"
EVENT_DELISTING = "delisting"
EVENT_MODIFIED = "modified"
EVENT_SUSPENDED = "suspended"
EVENT_REINSTATED = "reinstated"
EVENT_IPO = "ipo"  # only when the source states it (exchange IPO lists); FIRDS cannot
EVENT_TYPES = (
    EVENT_NEW_LISTING,
    EVENT_IPO,
    EVENT_DELISTING,
    EVENT_MODIFIED,
    EVENT_SUSPENDED,
    EVENT_REINSTATED,
)

STATUS_LISTED = "listed"
STATUS_DELISTED = "delisted"
STATUS_SUSPENDED = "suspended"
STATUSES = (STATUS_LISTED, STATUS_DELISTED, STATUS_SUSPENDED)


@dataclass
class ListingRecord:
    mic: str
    issuer_name: str
    source: str
    source_url: str
    isin: str | None = None
    issuer_lei: str | None = None
    symbol: str | None = None
    short_name: str | None = None
    cfi_code: str | None = None
    instrument_type: str = "share"
    currency: str | None = None
    admission_requested_date: date | None = None
    admission_approved_date: date | None = None
    first_trade_date: date | None = None
    termination_date: date | None = None
    status: str | None = None  # explicit source status, else derived from termination_date
    source_published_at: datetime | None = None
    explicit_event: str | None = None  # e.g. EVENT_IPO when the source says so
    quality_status: str = "ok"
    notes: list[str] = field(default_factory=list)

    @property
    def listing_key(self) -> str | None:
        """ISIN when valid, else a symbol key; None when neither is usable."""
        if self.isin and is_valid_isin(self.isin):
            return self.isin
        if self.symbol:
            return f"SYM:{self.symbol.strip().upper()}"
        return None

    def derived_status(self, today: date) -> str:
        if self.status in STATUSES:
            return self.status
        if self.termination_date is not None and self.termination_date <= today:
            return STATUS_DELISTED
        return STATUS_LISTED

    def record_hash(self) -> str:
        payload = {
            "issuer_name": self.issuer_name,
            "issuer_lei": self.issuer_lei,
            "symbol": self.symbol,
            "short_name": self.short_name,
            "cfi": self.cfi_code,
            "type": self.instrument_type,
            "ccy": self.currency,
            "req": _d(self.admission_requested_date),
            "appr": _d(self.admission_approved_date),
            "first": _d(self.first_trade_date),
            "term": _d(self.termination_date),
            "status": self.status,
        }
        return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def _d(value: date | None) -> str | None:
    return value.isoformat() if value else None


def event_key(listing_key: str, mic: str, event_type: str, event_date: date | None) -> str:
    raw = f"{listing_key}|{mic}|{event_type}|{_d(event_date) or ''}"
    return hashlib.sha256(raw.encode()).hexdigest()


def is_valid_isin(value: str) -> bool:
    """ISO 6166: 2 letters, 9 alphanumerics, 1 check digit (Luhn over letter-expanded digits)."""
    if not value or len(value) != 12 or not value[:2].isalpha() or not value[:11].isalnum():
        return False
    if not value[11].isdigit() or not value.isupper():
        return False
    digits = "".join(str(ord(ch) - 55) if ch.isalpha() else ch for ch in value)
    total = 0
    # Luhn: starting from the check digit (not doubled), double every second digit leftwards.
    for i, ch in enumerate(reversed(digits)):
        n = int(ch)
        if i % 2 == 1:
            n *= 2
            if n > 9:
                n -= 9
        total += n
    return total % 10 == 0
