"""Event feed: ordered, resumable, backfill-free stream of filings and listing events."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import select, update

from app.db.models import Filing, ListingEvent
from app.services import events as feed
from app.services.ingestion import ingest_company

SINCE = "&since=" + (datetime.now(UTC) - timedelta(days=1)).isoformat().replace("+00:00", "Z")


@pytest.fixture(autouse=True)
def _fast_feed(settings):
    settings.events_settle_seconds = 0
    settings.events_stream_poll_seconds = 0.02
    settings.events_stream_heartbeat_seconds = 0.1
    settings.events_stream_max_seconds = 0.4


def _new_filing(fake_sec, submissions, accession, form="8-K"):
    """Serve the submissions payload with one more, recent filing on top."""
    today = date.today().isoformat()
    recent = {k: list(v) for k, v in submissions["filings"]["recent"].items()}
    for col, val in [
        ("accessionNumber", accession),
        ("filingDate", today),
        ("reportDate", today),
        ("acceptanceDateTime", today + "T06:00:00.000Z"),
        ("form", form),
        ("primaryDocument", "x.htm"),
    ]:
        recent[col].insert(0, val)
    fake_sec.add(
        "https://data.sec.gov/submissions/CIK0000320193.json",
        {**submissions, "filings": {"recent": recent}},
    )


def _poll_all(client, auth, query="", limit=3):
    seen, cursor = [], None
    for _ in range(50):
        url = f"/v1/events?limit={limit}{query}" + (f"&after={cursor}" if cursor else SINCE)
        body = client.get(url, headers=auth).json()
        seen += body["data"]
        cursor = body["next_cursor"]
        if not body["has_more"]:
            return seen, cursor
    raise AssertionError("feed did not terminate")


def test_backfill_never_streams_but_new_filing_does(
    client, auth, db, sec_client, fake_sec, submissions_aapl
):
    ingest_company(db, sec_client, "320193")
    assert {f.stream_status for f in db.scalars(select(Filing))} == {"skipped"}
    assert client.get("/v1/events?" + SINCE[1:], headers=auth).json()["data"] == []

    _new_filing(fake_sec, submissions_aapl, "0000320193-26-000101")
    ingest_company(db, sec_client, "320193")
    data = client.get("/v1/events?" + SINCE[1:], headers=auth).json()["data"]
    assert len(data) == 1
    ev = data[0]
    assert ev["type"] == "sec.filing.detected" and ev["kind"] == "filing"
    assert ev["data"]["accession_number"] == "0000320193-26-000101"
    assert ev["data"]["company_name"] == "Apple Inc." and ev["data"]["ticker"] == "AAPL"
    assert ev["data"]["source_url"].startswith("https://www.sec.gov/")
    assert ev["stream_at"].endswith("Z")


def test_settle_delay_hides_rows_until_they_settle(
    client, auth, db, settings, sec_client, fake_sec, submissions_aapl
):
    ingest_company(db, sec_client, "320193")
    _new_filing(fake_sec, submissions_aapl, "0000320193-26-000102")
    ingest_company(db, sec_client, "320193")
    settings.events_settle_seconds = 3600
    assert client.get("/v1/events?" + SINCE[1:], headers=auth).json()["data"] == []
    settings.events_settle_seconds = 0
    assert len(client.get("/v1/events?" + SINCE[1:], headers=auth).json()["data"]) == 1


def test_pending_rows_wait_for_publication_sweep(add_listings, client, auth, db):
    add_listings(["AAA"])
    db.execute(update(ListingEvent).values(stream_status="pending", stream_at=None))
    db.commit()
    assert client.get("/v1/events?" + SINCE[1:], headers=auth).json()["data"] == []
    assert feed.publish_pending(db) == 1
    data = client.get("/v1/events?" + SINCE[1:], headers=auth).json()["data"]
    assert [e["type"] for e in data] == ["listing.new_listing"]
    assert data[0]["data"]["listing_key"] == "SYM:AAA" and data[0]["data"]["mic"] == "XPAR"


def test_paging_has_no_gaps_or_duplicates_when_timestamps_tie(
    add_listings, client, auth, db, sec_client
):
    ingest_company(db, sec_client, "320193")
    add_listings(["AAA", "BBB", "CCC", "DDD", "EEE"])
    tie = datetime.now(UTC) - timedelta(minutes=5)
    ids = [f.id for f in db.scalars(select(Filing))]
    assert len(ids) >= 4  # enough to span several pages
    db.execute(
        update(Filing)
        .where(Filing.id.in_(ids))
        .values(stream_status="published", stream_at=tie)
        .execution_options(synchronize_session=False)
    )
    db.execute(update(ListingEvent).values(stream_at=tie))
    db.commit()

    seen, cursor = _poll_all(client, auth, limit=3)
    total = len(ids) + 5
    assert len(seen) == total and len({e["id"] for e in seen}) == total
    assert [e["kind"] for e in seen] == ["filing"] * len(ids) + ["listing"] * 5
    assert [e["id"] for e in seen] == sorted(
        (e["id"] for e in seen), key=lambda i: feed.Cursor.decode(i)
    )
    # Caught up: the cursor returns nothing until something new is published.
    body = client.get(f"/v1/events?after={cursor}", headers=auth).json()
    assert body["data"] == [] and body["has_more"] is False
    add_listings(["FFF"])
    body = client.get(f"/v1/events?after={body['next_cursor']}", headers=auth).json()
    assert [e["data"]["listing_key"] for e in body["data"]] == ["SYM:FFF"]


def test_filters(add_listings, client, auth, db, sec_client, fake_sec, submissions_aapl):
    ingest_company(db, sec_client, "320193")
    _new_filing(fake_sec, submissions_aapl, "0000320193-26-000103", form="8-K")
    ingest_company(db, sec_client, "320193")
    add_listings(["AAA"], mic="XPAR")
    add_listings(["BBB"], mic="XETA")

    def kinds(q):
        r = client.get("/v1/events?" + q + SINCE, headers=auth)
        assert r.status_code == 200, r.text
        return [e["kind"] for e in r.json()["data"]]

    assert sorted(kinds("")) == ["filing", "listing", "listing"]
    assert kinds("types=filing") == ["filing"]
    assert kinds("cik=320193") == ["filing"]
    assert kinds("form_type=8-k") == ["filing"]
    assert kinds("form_type=10-K") == []
    assert kinds("mic=xeta") == ["listing"]
    assert kinds("event_type=new_listing") == ["listing", "listing"]
    for bad in ("cik=320193&mic=XPAR", "types=news", "cik=abc", "types=filing&mic=XPAR"):
        assert client.get("/v1/events?" + bad, headers=auth).status_code == 422, bad


def test_cursor_and_since_validation(client, auth):
    assert client.get("/v1/events?after=nonsense", headers=auth).json()["error"]["code"] == (
        "invalid_cursor"
    )
    old = (datetime.now(UTC) - timedelta(days=31)).isoformat().replace("+00:00", "Z")
    assert client.get(f"/v1/events?since={old}", headers=auth).status_code == 422
    assert client.get("/v1/events?since=2026-11-01T00:00:00", headers=auth).status_code == 422


def test_demo_key_polls_but_cannot_stream(client):
    assert client.get("/v1/events?limit=5", headers={"X-API-Key": "demo"}).status_code == 200
    assert client.get("/v1/events?limit=50", headers={"X-API-Key": "demo"}).status_code == 403
    r = client.get("/v1/events/stream", headers={"X-API-Key": "demo"})
    assert r.status_code == 401


def _read_sse(client, auth, query="", last_event_id=None):
    headers = dict(auth)
    if last_event_id:
        headers["Last-Event-ID"] = last_event_id
    with client.stream("GET", "/v1/events/stream?" + query, headers=headers) as r:
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/event-stream")
        text = "".join(r.iter_text())
    blocks = [b for b in text.split("\n\n") if b.strip()]
    events, last_id = [], None
    for block in blocks:
        fields = {}
        for line in block.split("\n"):
            if line.startswith(":") or ": " not in line:
                continue
            k, v = line.split(": ", 1)
            fields[k] = v
        if "id" in fields:
            last_id = fields["id"]
        if "data" in fields:
            events.append((fields["id"], fields["event"], json.loads(fields["data"])))
    return events, last_id, text


def test_sse_stream_delivers_and_resumes_with_last_event_id(add_listings, client, auth, db):
    add_listings(["AAA", "BBB"])
    events, last_id, text = _read_sse(client, auth, SINCE[1:])
    assert text.startswith("retry: ")
    assert [e[1] for e in events] == ["listing.new_listing", "listing.new_listing"]
    assert all(e[0] == e[2]["id"] for e in events)
    assert ": heartbeat" in text  # idle connection keeps moving Last-Event-ID

    # Reconnecting with the last id replays nothing old and picks up what is new.
    add_listings(["CCC"])
    events, _, _ = _read_sse(client, auth, last_event_id=last_id)
    assert [e[2]["data"]["listing_key"] for e in events] == ["SYM:CCC"]


def test_sse_default_start_is_now(add_listings, client, auth, db):
    add_listings(["AAA"])
    db.execute(update(ListingEvent).values(stream_at=datetime.now(UTC) - timedelta(minutes=1)))
    db.commit()
    events, _, _ = _read_sse(client, auth)
    assert events == []


def test_sse_concurrent_stream_limit(client, auth, db, api_key, settings):
    from app.api import routes_events
    from app.core.security import hash_api_key
    from app.db.models import ApiKey

    key = db.scalar(
        select(ApiKey).where(ApiKey.key_hash == hash_api_key(api_key, settings.api_key_pepper))
    )
    routes_events._open_streams[str(key.id)] = 1  # free plan allows one
    try:
        r = client.get("/v1/events/stream", headers=auth)
        assert r.status_code == 429 and r.json()["error"]["code"] == "stream_limit"
    finally:
        routes_events._open_streams.pop(str(key.id), None)
    events, _, _ = _read_sse(client, auth)
    assert routes_events._open_streams.get(str(key.id)) is None  # released on close


def test_cursor_roundtrip_and_order():
    at = datetime(2026, 11, 3, 10, 0, 0, 123456, tzinfo=UTC)
    import uuid

    a = feed.Cursor(at, "filing", uuid.uuid4())
    assert feed.Cursor.decode(a.encode()) == a
    assert feed.Cursor.start(at) < a < feed.Cursor(at, "listing", uuid.UUID(int=0))
    assert feed.Cursor(at, "listing", uuid.uuid4()) < feed.Cursor.end(at)
    with pytest.raises(ValueError):
        feed.Cursor.decode("bm9wZQ")
