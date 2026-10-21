"""Bounded HTTP fetching for register and exchange files: timeouts, size caps, on-disk cache.

Separate from the SEC client on purpose: different hosts, different fair-use rules, and
large zipped files that are cached by URL so a re-run on the same day costs no download.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import httpx

from app.core.config import Settings
from app.core.logging import log_event

logger = logging.getLogger("app.markets.http")


class MarketFetchError(Exception):
    pass


@dataclass
class FetchedFile:
    url: str
    path: Path
    size_bytes: int
    fetched_at: datetime
    from_cache: bool
    content_type: str | None


class MarketHttp:
    def __init__(
        self,
        settings: Settings,
        http: httpx.Client | None = None,
        cache_dir: str | Path | None = None,
        max_bytes: int = 200 * 1024 * 1024,
        min_interval_seconds: float = 1.0,
        sleep=time.sleep,
    ) -> None:
        self.settings = settings
        self.cache_dir = Path(cache_dir or settings.markets_cache_dir)
        self.max_bytes = max_bytes
        self.min_interval = min_interval_seconds
        self._sleep = sleep
        self._next_allowed = 0.0
        self._own = http is None
        self.http = http or httpx.Client(
            timeout=httpx.Timeout(settings.markets_timeout_seconds, connect=10.0),
            headers={
                "User-Agent": settings.markets_user_agent or settings.sec_user_agent,
                "Accept": "*/*",
            },
            follow_redirects=True,
        )
        self.http.headers["User-Agent"] = settings.markets_user_agent or settings.sec_user_agent

    def close(self) -> None:
        if self._own:
            self.http.close()

    def _throttle(self) -> None:
        now = time.monotonic()
        if now < self._next_allowed:
            self._sleep(self._next_allowed - now)
        self._next_allowed = time.monotonic() + self.min_interval

    def get_json(self, url: str, params: dict | None = None) -> object:
        self._throttle()
        try:
            resp = self.http.get(url, params=params)
        except httpx.HTTPError as exc:
            raise MarketFetchError(f"{type(exc).__name__} fetching {url}") from exc
        if resp.status_code != 200:
            raise MarketFetchError(f"HTTP {resp.status_code} fetching {url}")
        if len(resp.content) > self.max_bytes:
            raise MarketFetchError("response exceeds size limit")
        try:
            return resp.json()
        except ValueError as exc:
            raise MarketFetchError("response is not JSON") from exc

    def download(self, url: str, cache_key: str | None = None) -> FetchedFile:
        """Download to the cache directory (streamed, size-capped); reuse an existing copy."""
        key = hashlib.sha256((cache_key or url).encode()).hexdigest()[:32]
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        path = self.cache_dir / key
        meta_path = self.cache_dir / (key + ".json")
        if path.exists() and meta_path.exists():
            meta = json.loads(meta_path.read_text())
            return FetchedFile(
                url=url,
                path=path,
                size_bytes=path.stat().st_size,
                fetched_at=datetime.fromisoformat(meta["fetched_at"]),
                from_cache=True,
                content_type=meta.get("content_type"),
            )
        self._throttle()
        started = time.monotonic()
        size = 0
        tmp = path.with_suffix(".part")
        try:
            with self.http.stream("GET", url) as resp:
                if resp.status_code != 200:
                    raise MarketFetchError(f"HTTP {resp.status_code} fetching {url}")
                content_type = resp.headers.get("Content-Type")
                with tmp.open("wb") as fh:
                    for chunk in resp.iter_bytes():
                        size += len(chunk)
                        if size > self.max_bytes:
                            raise MarketFetchError("download exceeds size limit")
                        fh.write(chunk)
        except httpx.HTTPError as exc:
            tmp.unlink(missing_ok=True)
            raise MarketFetchError(f"{type(exc).__name__} fetching {url}") from exc
        except MarketFetchError:
            tmp.unlink(missing_ok=True)
            raise
        tmp.replace(path)
        fetched_at = datetime.now(UTC)
        meta_path.write_text(
            json.dumps(
                {"url": url, "fetched_at": fetched_at.isoformat(), "content_type": content_type}
            )
        )
        log_event(
            logger,
            logging.INFO,
            "market file downloaded",
            url=url,
            bytes=size,
            duration_ms=round((time.monotonic() - started) * 1000),
        )
        return FetchedFile(url, path, size, fetched_at, False, content_type)
