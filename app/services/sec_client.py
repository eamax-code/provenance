"""HTTP client for official SEC endpoints following SEC fair-access guidance.

- Descriptive User-Agent with contact email (required).
- Minimum interval between requests (default 0.25s = 4 req/s) via a process-wide lock.
- ETag / Last-Modified conditional requests with an on-disk JSON cache.
- Exponential backoff with jitter on 429/500/502/503/504 and 408; honours Retry-After.
- Bounded response size and timeouts. Never logs secrets.
"""

from __future__ import annotations

import hashlib
import json
import logging
import random
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from app.core.config import Settings
from app.core.logging import log_event

logger = logging.getLogger("app.sec_client")

RETRY_STATUSES = {408, 429, 500, 502, 503, 504}


class SecClientError(Exception):
    def __init__(self, message: str, status_code: int | None = None, url: str = "") -> None:
        super().__init__(message)
        self.status_code = status_code
        self.url = url


class SecNotFound(SecClientError):
    pass


class SecUnavailable(SecClientError):
    pass


@dataclass
class SecResponse:
    url: str
    status_code: int
    data: Any
    fetched_at: datetime
    from_cache: bool
    etag: str | None
    last_modified: datetime | None
    payload_hash: str
    retries: int


def normalize_cik(value: str | int) -> str:
    """Normalize a CIK to a 10-digit zero-padded string. Raises ValueError if invalid."""
    text = str(value).strip()
    if text.lower().startswith("cik"):
        text = text[3:]
    if not text or not text.isdigit() or len(text) > 10:
        raise ValueError("CIK must be 1-10 digits")
    if int(text) == 0:
        raise ValueError("CIK must be a positive integer")
    return text.zfill(10)


def is_cik_like(value: str) -> bool:
    try:
        normalize_cik(value)
        return True
    except ValueError:
        return False


def submissions_url(cik: str, base: str = "https://data.sec.gov") -> str:
    return f"{base}/submissions/CIK{normalize_cik(cik)}.json"


def company_facts_url(cik: str, base: str = "https://data.sec.gov") -> str:
    return f"{base}/api/xbrl/companyfacts/CIK{normalize_cik(cik)}.json"


def ticker_exchange_url(base: str = "https://www.sec.gov") -> str:
    return f"{base}/files/company_tickers_exchange.json"


def filing_index_url(cik: str, accession_number: str, base: str = "https://www.sec.gov") -> str:
    cik_int = str(int(normalize_cik(cik)))
    acc_nodash = accession_number.replace("-", "")
    return f"{base}/Archives/edgar/data/{cik_int}/{acc_nodash}/{accession_number}-index.html"


def _parse_http_date(value: str | None) -> datetime | None:
    if not value:
        return None
    from email.utils import parsedate_to_datetime

    try:
        dt = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


class _IntervalLimiter:
    """Process-wide minimum interval between SEC requests."""

    def __init__(self, min_interval: float) -> None:
        self.min_interval = min_interval
        self._lock = threading.Lock()
        self._next_allowed = 0.0

    def wait(self) -> None:
        with self._lock:
            now = time.monotonic()
            delay = self._next_allowed - now
            if delay > 0:
                time.sleep(delay)
                now = time.monotonic()
            self._next_allowed = now + self.min_interval


_limiters: dict[float, _IntervalLimiter] = {}
_limiters_lock = threading.Lock()


def _shared_limiter(min_interval: float) -> _IntervalLimiter:
    with _limiters_lock:
        if min_interval not in _limiters:
            _limiters[min_interval] = _IntervalLimiter(min_interval)
        return _limiters[min_interval]


class SecClient:
    def __init__(
        self,
        settings: Settings,
        http: httpx.Client | None = None,
        sleep=time.sleep,
        cache_dir: str | Path | None = None,
    ) -> None:
        ua = settings.sec_user_agent
        if not ua or "contact=" not in ua:
            raise ValueError("SEC_USER_AGENT must include a product name and contact=<email>")
        self.settings = settings
        self._sleep = sleep
        self._limiter = _shared_limiter(settings.sec_min_request_interval_seconds)
        self._cache_dir = Path(cache_dir or settings.sec_cache_dir)
        self._own_http = http is None
        self.http = http or httpx.Client(
            timeout=httpx.Timeout(settings.sec_timeout_seconds, connect=10.0),
            headers={
                "User-Agent": ua,
                "Accept": "application/json",
                "Accept-Encoding": "gzip, deflate",
            },
            follow_redirects=False,
        )

    def close(self) -> None:
        if self._own_http:
            self.http.close()

    # -- cache -------------------------------------------------------------------------
    def _cache_path(self, url: str) -> Path:
        name = hashlib.sha256(url.encode("utf-8")).hexdigest()
        return self._cache_dir / f"{name}.json"

    def _cache_read(self, url: str) -> dict | None:
        path = self._cache_path(url)
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text("utf-8"))
        except (OSError, ValueError):
            return None

    def _cache_write(self, url: str, entry: dict) -> None:
        try:
            self._cache_dir.mkdir(parents=True, exist_ok=True)
            tmp = self._cache_path(url).with_suffix(".tmp")
            tmp.write_text(json.dumps(entry), "utf-8")
            tmp.replace(self._cache_path(url))
        except OSError as exc:  # cache is best effort
            log_event(logger, logging.WARNING, "sec cache write failed", error=str(exc))

    # -- fetch -------------------------------------------------------------------------
    def get_json(self, url: str) -> SecResponse:
        cached = self._cache_read(url)
        headers: dict[str, str] = {}
        if cached:
            if cached.get("etag"):
                headers["If-None-Match"] = cached["etag"]
            if cached.get("last_modified_raw"):
                headers["If-Modified-Since"] = cached["last_modified_raw"]

        correlation_id = f"sec_{uuid.uuid4().hex[:12]}"
        attempt = 0
        while True:
            self._limiter.wait()
            started = time.monotonic()
            try:
                resp = self.http.get(url, headers=headers)
            except httpx.HTTPError as exc:
                duration = time.monotonic() - started
                log_event(
                    logger,
                    logging.WARNING,
                    "sec request error",
                    url=url,
                    error=type(exc).__name__,
                    attempt=attempt,
                    duration_ms=round(duration * 1000),
                    correlation_id=correlation_id,
                )
                if attempt >= self.settings.sec_max_retries:
                    raise SecUnavailable("SEC endpoint unavailable after retries", url=url) from exc
                self._sleep(self._backoff(attempt, None))
                attempt += 1
                continue

            duration = time.monotonic() - started
            log_event(
                logger,
                logging.INFO,
                "sec request",
                url=url,
                status=resp.status_code,
                attempt=attempt,
                duration_ms=round(duration * 1000),
                correlation_id=correlation_id,
            )
            now = datetime.now(UTC)

            if resp.status_code == 304 and cached:
                return SecResponse(
                    url=url,
                    status_code=304,
                    data=cached["body"],
                    fetched_at=now,
                    from_cache=True,
                    etag=cached.get("etag"),
                    last_modified=_parse_http_date(cached.get("last_modified_raw")),
                    payload_hash=cached["payload_hash"],
                    retries=attempt,
                )
            if resp.status_code in RETRY_STATUSES:
                if attempt >= self.settings.sec_max_retries:
                    raise SecUnavailable(
                        f"SEC endpoint returned {resp.status_code} after retries",
                        status_code=resp.status_code,
                        url=url,
                    )
                self._sleep(self._backoff(attempt, resp.headers.get("Retry-After")))
                attempt += 1
                continue
            if resp.status_code == 404:
                raise SecNotFound("Resource not found at SEC", status_code=404, url=url)
            if resp.status_code >= 400:
                raise SecClientError(
                    f"SEC endpoint returned {resp.status_code}",
                    status_code=resp.status_code,
                    url=url,
                )
            if resp.status_code in (301, 302, 303, 307, 308):
                raise SecClientError(
                    "Unexpected redirect from SEC endpoint", status_code=resp.status_code, url=url
                )

            body_bytes = resp.content
            if len(body_bytes) > self.settings.sec_max_response_bytes:
                raise SecClientError("SEC response exceeded size limit", url=url)
            try:
                data = json.loads(body_bytes)
            except ValueError as exc:
                raise SecClientError("SEC response was not valid JSON", url=url) from exc

            payload_hash = hashlib.sha256(body_bytes).hexdigest()
            etag = resp.headers.get("ETag")
            lm_raw = resp.headers.get("Last-Modified")
            self._cache_write(
                url,
                {
                    "etag": etag,
                    "last_modified_raw": lm_raw,
                    "body": data,
                    "payload_hash": payload_hash,
                    "fetched_at": now.isoformat(),
                },
            )
            return SecResponse(
                url=url,
                status_code=resp.status_code,
                data=data,
                fetched_at=now,
                from_cache=False,
                etag=etag,
                last_modified=_parse_http_date(lm_raw),
                payload_hash=payload_hash,
                retries=attempt,
            )

    def _backoff(self, attempt: int, retry_after: str | None) -> float:
        if retry_after:
            try:
                return min(float(retry_after), 120.0)
            except ValueError:
                parsed = _parse_http_date(retry_after)
                if parsed:
                    return max(0.0, min((parsed - datetime.now(UTC)).total_seconds(), 120.0))
        base = min(60.0, 1.0 * (2**attempt))
        return base + random.uniform(0, base * 0.25)

    # -- convenience -----------------------------------------------------------------------
    def fetch_submissions(self, cik: str) -> SecResponse:
        return self.get_json(submissions_url(cik, self.settings.sec_base_data_url))

    def fetch_company_facts(self, cik: str) -> SecResponse:
        return self.get_json(company_facts_url(cik, self.settings.sec_base_data_url))

    def fetch_ticker_exchange(self) -> SecResponse:
        return self.get_json(ticker_exchange_url(self.settings.sec_base_www_url))
