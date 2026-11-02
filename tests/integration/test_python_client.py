"""The Python client in clients/python, exercised against the real app."""

from __future__ import annotations

import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "clients" / "python" / "src"))

from provenance_client import Client, ProvenanceError  # noqa: E402
from provenance_client.client import _sse_blocks  # noqa: E402

from tests.conftest import REVENUE_ORIGINAL as ORIGINAL  # noqa: E402
from tests.conftest import REVENUE_RESTATED as RESTATED  # noqa: E402
from tests.conftest import REVENUE_TAG as TAG  # noqa: E402


@pytest.fixture(autouse=True)
def _fast_feed(settings):
    settings.events_settle_seconds = 0
    settings.events_stream_poll_seconds = 0.02
    settings.events_stream_heartbeat_seconds = 0.1
    settings.events_stream_max_seconds = 0.3


@pytest.fixture
def pc(client, api_key):
    return Client(api_key=api_key, base_url="http://testserver", http=client, sleep=lambda s: None)


def test_point_in_time_facts_through_client(pc, restated_aapl):
    def fy23(rows):
        return next(r for r in rows if r["period_end"] == "2023-09-30" and r["source_tag"] == TAG)

    assert fy23(pc.facts("320193", "revenue", as_of=date(2024, 1, 15)))["value"] == ORIGINAL
    assert fy23(pc.facts(320193, "revenue"))["value"] == RESTATED
    rows = pc.screen("revenue", 2023, as_of="2024-01-15")
    assert rows[0]["cik"] == "0000320193" and rows[0]["value"] == ORIGINAL


def test_search_profile_filings_and_pagination(pc, ingested_aapl):
    assert pc.search("AAPL")[0]["cik"] == "0000320193"
    assert pc.company("320193")["legal_name"] == "Apple Inc."
    filings = list(pc.filings("320193"))
    assert filings and all(f["source_url"].startswith("https://www.sec.gov/") for f in filings)
    assert len(list(pc.filings("320193", max_rows=2))) == 2
    assert [c["cik"] for c in pc.companies(ingested=True)] == ["0000320193"]


def test_errors_carry_code_and_request_id(pc, client):
    with pytest.raises(ProvenanceError) as exc:
        pc.facts("320193", metric="ebitda")
    assert exc.value.status in (404, 422) and exc.value.code and exc.value.request_id
    bad = Client(api_key="wrong", base_url="http://testserver", http=client)
    with pytest.raises(ProvenanceError) as exc:
        bad.search("AAPL")
    assert exc.value.status == 401 and exc.value.code == "invalid_api_key"


def test_retries_429_using_retry_after():
    calls, sleeps = [], []

    def handler(request):
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(
                429,
                headers={"Retry-After": "3"},
                json={"error": {"code": "rate_limited", "message": "slow", "request_id": "r1"}},
            )
        return httpx.Response(200, json={"data": [{"cik": "1"}], "meta": {"has_more": False}})

    c = Client(
        api_key="k",
        base_url="http://x",
        http=httpx.Client(transport=httpx.MockTransport(handler)),
        sleep=sleeps.append,
    )
    assert c.search("a") == [{"cik": "1"}]
    assert sleeps == [3.0] and calls[0].headers["X-API-Key"] == "k"


def test_events_polling_and_resume(add_listings, pc, db):
    add_listings(["AAA", "BBB"])
    since = datetime.now(UTC) - timedelta(hours=1)
    got = [e["data"]["listing_key"] for e in pc.events(since=since)]
    assert sorted(got) == ["SYM:AAA", "SYM:BBB"]  # same stream_at: ordered by id
    cursor = pc.last_cursor
    assert list(pc.events(after=cursor)) == []
    add_listings(["CCC"])
    assert [e["data"]["listing_key"] for e in pc.events(after=cursor)] == ["SYM:CCC"]


def test_stream_yields_events_and_keeps_cursor(add_listings, pc, db):
    add_listings(["AAA"])
    since = datetime.now(UTC) - timedelta(hours=1)
    events = list(pc.stream(since=since, reconnect=False))
    assert [e["type"] for e in events] == ["listing.new_listing"]
    assert pc.last_cursor  # advanced by events and heartbeats
    add_listings(["BBB"])
    resumed = list(pc.stream(after=pc.last_cursor, reconnect=False))
    assert [e["data"]["listing_key"] for e in resumed] == ["SYM:BBB"]


def test_stream_reconnects_after_server_closes(add_listings, pc, db):
    add_listings(["AAA"])
    since = datetime.now(UTC) - timedelta(hours=1)
    it = pc.stream(since=since)
    assert next(it)["data"]["listing_key"] == "SYM:AAA"
    add_listings(["BBB"])
    # The first connection ends after the max duration; the client reconnects from its id.
    assert next(it)["data"]["listing_key"] == "SYM:BBB"
    it.close()


def test_sse_parser():
    lines = ["retry: 3000", ": connected", "", "id: c1", "event: x", 'data: {"a":1}', "", ": hb"]
    lines += ["id: c2", ""]
    assert list(_sse_blocks(iter(lines))) == [
        {"retry": "3000"},
        {"id": "c1", "event": "x", "data": '{"a":1}'},
        {"id": "c2"},
    ]


def test_to_dataframe_flattens_events():
    pd = pytest.importorskip("pandas")
    from provenance_client import to_dataframe

    df = to_dataframe([{"id": "1", "data": {"cik": "0000320193"}}])
    assert isinstance(df, pd.DataFrame) and df.loc[0, "data.cik"] == "0000320193"
