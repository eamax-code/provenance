"""A thin, dependency-light client: httpx for HTTP, pandas only if you ask for a DataFrame."""

from __future__ import annotations

import json
import os
import time
from collections.abc import Callable, Iterator
from datetime import date, datetime
from typing import Any

import httpx

DEFAULT_BASE_URL = "http://127.0.0.1:8000"
_RETRY_STATUSES = {429, 500, 502, 503, 504}


class ProvenanceError(Exception):
    """An API error, carrying the stable error code and the request id for support."""

    def __init__(
        self,
        status: int,
        code: str,
        message: str,
        request_id: str | None = None,
        retry_after: float | None = None,
    ) -> None:
        super().__init__(f"{status} {code}: {message}")
        self.status = status
        self.code = code
        self.message = message
        self.request_id = request_id
        self.retry_after = retry_after


def _param(value: Any) -> Any:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, datetime):
        return value.isoformat().replace("+00:00", "Z")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, list | tuple | set):
        return ",".join(str(v) for v in value)
    return value


def _clean(params: dict[str, Any]) -> dict[str, Any]:
    return {k: _param(v) for k, v in params.items() if v is not None and v != ""}


class Client:
    """Provenance API client.

    >>> client = Client(api_key="...", base_url="https://api.example.com")
    >>> facts = client.facts("320193", metric="revenue", as_of="2024-01-15")
    """

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        *,
        timeout: float = 30.0,
        max_retries: int = 2,
        http: httpx.Client | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.api_key = api_key or os.environ.get("PROVENANCE_API_KEY") or "demo"
        self.base_url = base_url or os.environ.get("PROVENANCE_BASE_URL") or DEFAULT_BASE_URL
        self.base_url = self.base_url.rstrip("/")
        self.max_retries = max_retries
        self._sleep = sleep
        self._http = http or httpx.Client(timeout=timeout)
        self._owns_http = http is None
        self.last_cursor: str | None = None

    def close(self) -> None:
        if self._owns_http:
            self._http.close()

    def __enter__(self) -> Client:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # ---- HTTP -----------------------------------------------------------------------------

    @property
    def _headers(self) -> dict[str, str]:
        return {"X-API-Key": self.api_key, "Accept": "application/json"}

    def get(self, path: str, **params: Any) -> dict:
        """GET a path under the API, retrying 429/5xx with Retry-After or backoff."""
        attempt = 0
        while True:
            try:
                r = self._http.get(
                    self.base_url + path, params=_clean(params), headers=self._headers
                )
            except httpx.TransportError:
                if attempt >= self.max_retries:
                    raise
                attempt += 1
                self._sleep(min(30.0, 2.0**attempt))
                continue
            if r.status_code < 400:
                return r.json()
            error = _error(r)
            if r.status_code in _RETRY_STATUSES and attempt < self.max_retries:
                wait = error.retry_after if error.retry_after is not None else 2.0 ** (attempt + 1)
                if wait <= 60:
                    attempt += 1
                    self._sleep(wait)
                    continue
            raise error

    def _pages(self, path: str, page_size: int, max_rows: int | None, **params: Any):
        offset, returned = 0, 0
        while True:
            body = self.get(path, limit=page_size, offset=offset, **params)
            for row in body["data"]:
                yield row
                returned += 1
                if max_rows is not None and returned >= max_rows:
                    return
            meta = body.get("meta", {})
            if not meta.get("has_more") or meta.get("next_offset") is None:
                return
            offset = meta["next_offset"]

    # ---- US companies (SEC) ---------------------------------------------------------------

    def search(self, q: str, limit: int = 10) -> list[dict]:
        return self.get("/v1/companies/search", q=q, limit=limit)["data"]

    def companies(self, max_rows: int | None = None, **filters: Any) -> Iterator[dict]:
        """All companies matching filters (exchange, sic, state, ingested, sort)."""
        return self._pages("/v1/companies", 200, max_rows, **filters)

    def company(self, cik: str | int, wait_seconds: float = 60.0) -> dict:
        """Company profile. Waits while the API ingests an unknown company (HTTP 202)."""
        deadline = time.monotonic() + wait_seconds
        while True:
            r = self._http.get(f"{self.base_url}/v1/companies/{cik}", headers=self._headers)
            if r.status_code == 202 and time.monotonic() < deadline:
                self._sleep(float(r.headers.get("Retry-After", "5")))
                continue
            if r.status_code >= 400:
                raise _error(r)
            return r.json()

    def filings(
        self,
        cik: str | int,
        form_type: str | None = None,
        since: date | str | None = None,
        max_rows: int | None = None,
    ) -> Iterator[dict]:
        return self._pages(
            f"/v1/companies/{cik}/filings", 100, max_rows, form_type=form_type, since=since
        )

    def facts(
        self,
        cik: str | int,
        metric: str | None = None,
        period: str = "annual",
        *,
        as_of: date | str | None = None,
        include_derived: bool = False,
        include_all_observations: bool = False,
        **filters: Any,
    ) -> list[dict]:
        """Normalized facts. as_of returns only what had been filed with the SEC by that date."""
        return list(
            self._pages(
                f"/v1/companies/{cik}/facts",
                100,
                None,
                metric=metric,
                period=period,
                as_of=as_of,
                include_derived=include_derived or None,
                include_all_observations=include_all_observations or None,
                **filters,
            )
        )

    def screen(
        self,
        metric: str,
        year: int,
        period: str = "annual",
        *,
        as_of: date | str | None = None,
        max_rows: int | None = None,
        **filters: Any,
    ) -> list[dict]:
        return list(
            self._pages(
                "/v1/facts/screen",
                200,
                max_rows,
                metric=metric,
                year=year,
                period=period,
                as_of=as_of,
                **filters,
            )
        )

    # ---- International listings --------------------------------------------------------

    def listing_events(self, max_rows: int | None = None, **filters: Any) -> Iterator[dict]:
        """Listing events (type, region, mic, since, detected_since)."""
        return self._pages("/v1/markets/events", 200, max_rows, **filters)

    # ---- Event feed ---------------------------------------------------------------------

    def events_page(self, after: str | None = None, **params: Any) -> dict:
        """One page of the feed: {"data", "next_cursor", "has_more"}."""
        return self.get("/v1/events", after=after, **params)

    def events(
        self,
        after: str | None = None,
        since: datetime | str | None = None,
        *,
        follow: bool = False,
        interval: float = 10.0,
        **filters: Any,
    ) -> Iterator[dict]:
        """Read the feed from a cursor (or a start time). With follow=True, keep polling.

        The cursor of the last event read is kept in `self.last_cursor`; store it to resume.
        """
        cursor = after
        while True:
            params = dict(filters, limit=100)
            if cursor is None and since is not None:
                params["since"] = since
            page = self.events_page(after=cursor, **params)
            for event in page["data"]:
                self.last_cursor = event["id"]
                yield event
            cursor = page["next_cursor"]
            self.last_cursor = cursor
            if page["has_more"]:
                continue
            if not follow:
                return
            self._sleep(interval)

    def stream(
        self,
        after: str | None = None,
        since: datetime | str | None = None,
        *,
        reconnect: bool = True,
        **filters: Any,
    ) -> Iterator[dict]:
        """Follow the feed over Server-Sent Events, reconnecting from the last id received.

        Yields event dicts as returned by the polling endpoint. `self.last_cursor` always holds
        the position to resume from, including after idle heartbeats.
        """
        last_id = after
        failures = 0
        while True:
            params = _clean(dict(filters, since=since if last_id is None else None))
            headers = {**self._headers, "Accept": "text/event-stream"}
            if last_id:
                headers["Last-Event-ID"] = last_id
            try:
                with self._http.stream(
                    "GET",
                    self.base_url + "/v1/events/stream",
                    params=params,
                    headers=headers,
                    timeout=httpx.Timeout(30.0, read=None),
                ) as r:
                    if r.status_code >= 400:
                        r.read()
                        error = _error(r)
                        if r.status_code not in _RETRY_STATUSES or not reconnect:
                            raise error
                        self._sleep(error.retry_after or min(60.0, 2.0 ** (failures + 1)))
                        failures += 1
                        continue
                    failures = 0
                    for block in _sse_blocks(r.iter_lines()):
                        if "id" in block:
                            last_id = block["id"]
                            self.last_cursor = last_id
                        if "data" in block:
                            yield json.loads(block["data"])
            except httpx.TransportError:
                if not reconnect:
                    raise
                failures += 1
                self._sleep(min(60.0, 2.0**failures))
                continue
            if not reconnect:
                return


def _sse_blocks(lines: Iterator[str]) -> Iterator[dict[str, str]]:
    block: dict[str, str] = {}
    for line in lines:
        if line == "":
            if block:
                yield block
            block = {}
            continue
        if line.startswith(":"):
            continue
        name, _, value = line.partition(":")
        value = value[1:] if value.startswith(" ") else value
        if name == "data" and "data" in block:
            block["data"] += "\n" + value
        elif name in ("id", "event", "data", "retry"):
            block[name] = value
    if block:
        yield block


def _error(r: httpx.Response) -> ProvenanceError:
    retry_after = r.headers.get("Retry-After")
    try:
        body = r.json()["error"]
        code, message, rid = (
            body.get("code", "error"),
            body.get("message", ""),
            body.get("request_id"),
        )
    except (ValueError, KeyError, TypeError):
        code, message, rid = "error", r.text[:200], r.headers.get("X-Request-ID")
    return ProvenanceError(
        r.status_code,
        code,
        message,
        request_id=rid,
        retry_after=float(retry_after) if retry_after and retry_after.isdigit() else None,
    )


def to_dataframe(rows: list[dict] | Iterator[dict]):
    """Rows (or feed events, whose `data` is flattened) as a pandas DataFrame."""
    try:
        import pandas as pd
    except ImportError as exc:  # pragma: no cover - depends on the environment
        raise ImportError("pip install 'provenance-client[pandas]' to use to_dataframe") from exc
    return pd.json_normalize(list(rows))
