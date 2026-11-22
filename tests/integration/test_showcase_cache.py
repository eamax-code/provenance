"""Keyless showcase reads are served from a server-side cache until the data changes, and a
repeat view does not count against the demo limits."""

from __future__ import annotations

import pytest

from app.services import showcase_cache

DEMO = {"X-API-Key": "demo"}
OVERVIEW = "/v1/companies/320193/overview"


@pytest.fixture(autouse=True)
def _fresh():
    from app.api import dependencies

    for limiter in (dependencies.demo_minute_limiter, dependencies.demo_day_limiter):
        limiter.reset()
    showcase_cache.clear()
    yield
    showcase_cache.clear()


def test_repeat_views_are_cached_and_not_counted(client, ingested_aapl, settings, monkeypatch):
    monkeypatch.setattr(settings, "demo_rate_limit_per_minute", 2)
    first = client.get(OVERVIEW, headers=DEMO)
    assert first.status_code == 200 and first.headers["X-Cache"] == "miss"
    for _ in range(5):  # over the limit of 2, but every repeat is a cache hit
        again = client.get(OVERVIEW, headers=DEMO)
        assert again.status_code == 200 and again.headers["X-Cache"] == "hit"
        assert again.json() == first.json()
        assert again.headers["X-Request-ID"] != first.headers["X-Request-ID"]
    # the query string is part of the key (api_key itself is not)
    assert client.get(OVERVIEW + "?api_key=demo").headers["X-Cache"] == "hit"
    assert client.get("/v1/companies/320193/timeline", headers=DEMO).headers["X-Cache"] == "miss"
    # only the two misses counted: the third uncached read is over the limit
    assert client.get("/v1/companies/320193/statements/income", headers=DEMO).status_code == 429


def test_a_data_change_empties_the_cache(client, ingested_aapl, monkeypatch):
    assert client.get(OVERVIEW, headers=DEMO).headers["X-Cache"] == "miss"
    assert client.get(OVERVIEW, headers=DEMO).headers["X-Cache"] == "hit"
    monkeypatch.setattr(showcase_cache, "_read_version", lambda: "after a load")
    monkeypatch.setattr(showcase_cache, "RECHECK_SECONDS", 0)
    assert client.get(OVERVIEW, headers=DEMO).headers["X-Cache"] == "miss"
    assert client.get(OVERVIEW, headers=DEMO).headers["X-Cache"] == "hit"


def test_keyed_requests_and_errors_are_never_cached(client, ingested_aapl, auth):
    assert client.get(OVERVIEW, headers=DEMO).headers["X-Cache"] == "miss"
    keyed = client.get(OVERVIEW, headers=auth)
    assert keyed.status_code == 200 and "X-Cache" not in keyed.headers
    other = client.get("/v1/companies/789019/overview", headers=DEMO)  # not in the showcase
    assert other.status_code == 403 and "X-Cache" not in other.headers
    assert client.get("/v1/companies/789019/overview", headers=DEMO).status_code == 403
    search = client.get("/v1/companies/search?q=apple", headers=DEMO)  # not a showcase page
    assert search.status_code == 200 and "X-Cache" not in search.headers


def test_paths_covered():
    for path in (
        "/v1/companies/320193/overview", "/v1/companies/320193/statements/income",
        "/v1/companies/320193/timeline", "/v1/companies/320193/insiders",
        "/v1/companies/320193/insider-transactions", "/v1/companies/320193/holders",
        "/v1/companies/320193/ownership", "/v1/facts/screen",
    ):  # fmt: skip
        assert showcase_cache.PATHS.match(path), path
    assert not showcase_cache.PATHS.match("/v1/companies/320193/facts")
    assert not showcase_cache.PATHS.match("/v1/watchlists/wl_1/rows")
