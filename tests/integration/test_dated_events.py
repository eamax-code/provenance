"""sec.lockup_expiry: emitted on the day; past dates found first time are backfill."""

from __future__ import annotations

import json
from datetime import date, timedelta

from sqlalchemy import select

from app.db.models import Company, DatedEvent, IpoTerms, NotificationDelivery, utcnow
from app.services import dated_events, events, notifications

TODAY = date.today()


def _ipo(db, cik, accn, expiry):
    db.add(Company(cik=cik, legal_name=f"Co {cik}", quality_status="ok",
                   source_url="https://www.sec.gov/", first_detected_at=utcnow()))  # fmt: skip
    db.add(IpoTerms(
        cik=cik, accession_number=accn, form_type="424B4", filing_date=expiry - timedelta(180),
        source_url=f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/x.htm",
        extractor_version="ipo-terms-1",
        terms=json.dumps({
            "lockup_days": {"value": 180, "evidence": "for a period of 180 days", "derived": False},
            "lockup_expiry": {"value": expiry.isoformat(), "evidence": "Derived", "derived": True},
        }),
    ))  # fmt: skip


def test_lockup_expiry_on_the_day(db, client, auth, settings):
    settings.events_settle_seconds = 0
    _ipo(db, "0000000021", "a-1", TODAY)  # today: news
    _ipo(db, "0000000022", "b-1", TODAY - timedelta(days=40))  # long past: backfill
    _ipo(db, "0000000023", "c-1", TODAY + timedelta(days=30))  # not yet
    db.commit()
    hook = {"destination": "https://hooks.example.com/x"}
    for k in db.scalars(select(__import__("app.db.models", fromlist=["ApiKey"]).ApiKey)):
        k.plan = "builder"
    db.commit()
    assert client.post("/v1/type-watches", json={"event_types": ["sec.lockup_expiry"], **hook},
                       headers=auth).status_code == 201  # fmt: skip
    rows = dated_events.emit_due(db, TODAY)
    db.commit()
    by = {r.cik: r.stream_status for r in rows}
    assert by == {"0000000021": "pending", "0000000022": "skipped"}
    assert dated_events.emit_due(db, TODAY) == []  # idempotent
    assert notifications.create_dated_deliveries(db, rows) == 1
    db.commit()
    events.publish_pending(db)
    since = (utcnow() - timedelta(hours=1)).isoformat().replace("+00:00", "Z")
    feed = client.get(f"/v1/events?event_type=sec.lockup_expiry&since={since}",
                      headers=auth).json()["data"]  # fmt: skip
    assert [(e["kind"], e["data"]["cik"]) for e in feed] == [("calendar", "0000000021")]
    assert "180-day IPO lock-up ends" in feed[0]["data"]["label"]
    d = db.scalar(select(NotificationDelivery))
    target = notifications._target(db, d, utcnow())
    assert target[1]["event_type"] == "sec.lockup_expiry" and target[2] is None
    assert db.scalar(select(DatedEvent).where(DatedEvent.cik == "0000000023")) is None
