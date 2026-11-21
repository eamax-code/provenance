"""T-01: type watches across companies, with a universe filter and hourly batches."""

from __future__ import annotations

import json
from datetime import timedelta

import pytest
from sqlalchemy import select

from app.db.models import ApiKey, Company, NotificationDelivery, TypeWatch, utcnow
from app.services import notifications
from app.services.ingestion import ingest_company
from tests.integration.test_events import _new_filing

HOOK = "https://hooks.example.com/alerts"


@pytest.fixture
def builder(db, api_key):
    for k in db.scalars(select(ApiKey)):
        k.plan = "builder"
    db.commit()


class Sender:
    def __init__(self):
        self.sent = []

    def send(self, url, body, headers):
        self.sent.append((url, json.loads(body), headers))

        class R:
            status_code = 200

        return R()


def test_type_watches_need_builder_and_valid_types(client, auth, db):
    body = {"event_types": ["sec.restatement"], "destination": HOOK}
    r = client.post("/v1/type-watches", json=body, headers=auth)
    assert r.status_code == 403 and r.json()["error"]["code"] == "plan_upgrade_required"
    for k in db.scalars(select(ApiKey)):
        k.plan = "builder"
    db.commit()
    bad = client.post("/v1/type-watches", json={**body, "event_types": ["sec.x"]}, headers=auth)
    assert bad.status_code == 422
    ok = client.post("/v1/type-watches", json=body, headers=auth)
    assert ok.status_code == 201, ok.text
    w = ok.json()
    assert w["delivery_mode"] == "immediate" and len(w["webhook_secret"]) == 64
    busy = client.post("/v1/type-watches", json={**body, "event_types": ["sec.results"]},
                       headers=auth).json()  # fmt: skip
    assert busy["delivery_mode"] == "hourly"  # no universe: batched
    narrow = client.post(
        "/v1/type-watches", json={**body, "event_types": ["sec.results"], "sic_prefix": "35"},
        headers=auth,
    ).json()  # fmt: skip
    assert narrow["delivery_mode"] == "immediate"
    listed = client.get("/v1/type-watches", headers=auth).json()["data"]
    assert len(listed) == 3 and "webhook_secret" not in listed[0]
    usage = client.get("/v1/developer/usage", headers=auth).json()
    assert usage is not None
    gone = client.delete(f"/v1/type-watches/{w['id']}", headers=auth)
    assert gone.status_code == 200 and gone.json()["is_active"] is False


def test_universe_filter_matches_company_fields():
    c = Company(cik="0000320193", legal_name="Apple Inc.", sic_code="3571", exchange="Nasdaq",
                filer_category="Large accelerated filer")  # fmt: skip
    w = TypeWatch(event_types="sec.restatement,sec.results", sic_prefix="35", exchange="nasdaq")
    assert notifications.type_watch_matches(w, {"sec.results"}, c)
    assert not notifications.type_watch_matches(w, {"sec.bankruptcy"}, c)
    assert not notifications.type_watch_matches(
        TypeWatch(event_types="sec.results", sic_prefix="28"), {"sec.results"}, c
    )
    assert notifications.type_watch_matches(
        TypeWatch(event_types="sec.results", ciks="0000320193"), {"sec.results"}, c
    )  # fmt: skip
    assert not notifications.type_watch_matches(
        TypeWatch(event_types="sec.results", ciks="0000789019"), {"sec.results"}, c
    )  # fmt: skip


def test_rare_types_deliver_at_once_and_busy_types_batch_hourly(
    client, auth, db, settings, sec_client, fake_sec, submissions_aapl, builder
):
    ingest_company(db, sec_client, "320193")  # backfill: never notifies
    rare = client.post(
        "/v1/type-watches",
        json={"event_types": ["sec.restatement"], "destination": HOOK},
        headers=auth,
    ).json()
    busy = client.post(
        "/v1/type-watches", json={"event_types": ["sec.results"], "destination": HOOK}, headers=auth
    ).json()
    assert db.scalars(select(NotificationDelivery)).all() == []  # fmt: skip

    _new_filing(fake_sec, submissions_aapl, "0000320193-26-000301", form="8-K", items="4.02")
    ingest_company(db, sec_client, "320193")
    _new_filing(fake_sec, submissions_aapl, "0000320193-26-000302", form="8-K", items="2.02")
    ingest_company(db, sec_client, "320193")
    _new_filing(fake_sec, submissions_aapl, "0000320193-26-000303", form="8-K", items="2.02")
    ingest_company(db, sec_client, "320193")
    rows = db.scalars(select(NotificationDelivery)).all()
    assert {str(r.type_watch_id) for r in rows} == {rare["id"], busy["id"]}
    assert len(rows) == 3

    sender, now = Sender(), utcnow()
    notifications.deliver_pending(db, settings, sender, now=now)
    assert len(sender.sent) == 1  # the restatement goes now; results wait for the hour
    _, payload, headers = sender.sent[0]
    assert payload["data"]["event_types"] == ["sec.restatement"]
    assert payload["data"]["type_watch_id"] == rare["id"] and headers["X-Signature"]

    notifications.deliver_pending(db, settings, sender, now=now + timedelta(hours=1, minutes=1))
    assert len(sender.sent) == 2
    _, batch, headers = sender.sent[1]
    assert batch["event_type"] == "sec.filing.batch" and batch["data"]["count"] == 2
    assert headers["X-Event-Id"] == batch["event_id"]
    assert {e["data"]["accession_number"] for e in batch["data"]["events"]} == {
        "0000320193-26-000302", "0000320193-26-000303"
    }  # fmt: skip
    assert {r.status for r in db.scalars(select(NotificationDelivery))} == {"delivered"}
