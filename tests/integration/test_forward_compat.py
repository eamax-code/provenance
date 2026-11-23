"""A row written by newer code (an event type this code does not know) never turns a read into
a 500: the feed shows it plainly, the timeline and the home strip leave it out (2026-11-24: old
code on a review server crashed on the new trading-plan events)."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta

from app.db.models import DatedEvent

CIK = "0000320193"


def _future_event(db):
    now = datetime.now(UTC)
    db.add(DatedEvent(
        cik=CIK, event_type="sec.from_a_newer_release", event_date=date.today(),
        accession_number="0000320193-26-999999", detail=json.dumps({"anything": 1}),
        source_url="https://www.sec.gov/Archives/edgar/data/320193/x-index.html",
        stream_status="published", stream_at=now - timedelta(minutes=10), created_at=now,
    ))  # fmt: skip
    db.commit()


def test_unknown_dated_event_type_never_breaks_a_read(client, auth, db, ingested_aapl):
    _future_event(db)
    since = (datetime.now(UTC) - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    r = client.get(f"/v1/events?since={since}", headers=auth)
    assert r.status_code == 200
    shown = [e for e in r.json()["data"] if e["type"] == "sec.from_a_newer_release"]
    assert shown and shown[0]["data"]["label"] == "sec.from_a_newer_release"
    tl = client.get(f"/v1/companies/{CIK}/timeline?limit=200", headers=auth)
    assert tl.status_code == 200
    assert all(i["event_type"] != "sec.from_a_newer_release" for i in tl.json()["data"])
    strip = client.get("/v1/public/events")
    assert strip.status_code == 200
    assert "sec.from_a_newer_release" not in strip.text
