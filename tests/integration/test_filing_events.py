"""D-05: what a filing means (8-K items and form types) on the feed, watches and webhooks."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.db.models import NotificationDelivery
from app.services import filing_events
from app.services.ingestion import ingest_company
from app.services.notifications import build_event_payload
from tests.integration.test_events import SINCE, _new_filing


@pytest.fixture(autouse=True)
def _fast_feed(settings):
    settings.events_settle_seconds = 0


def test_types_come_only_from_form_and_declared_items():
    assert filing_events.types_for("8-K", "4.02,9.01") == ["sec.restatement"]
    assert filing_events.types_for("8-K/A", "2.02,5.07") == ["sec.results", "sec.shareholder_vote"]
    assert filing_events.types_for("10-Q", "4.02") == []  # items mean nothing outside an 8-K
    assert filing_events.types_for("NT 10-K", None) == ["sec.late_filing"]
    assert filing_events.types_for("25-NSE", "") == ["sec.delisting"]
    assert filing_events.types_for("15-12G", None) == ["sec.deregistration"]
    assert filing_events.types_for("SC TO-T", None) == ["sec.tender_offer"]
    assert filing_events.types_for("DEFM14A", None) == ["sec.merger_proxy"]
    assert filing_events.types_for("8-K", ["1.03"]) == ["sec.bankruptcy"]
    for name, t in filing_events.FILING_EVENT_TYPES.items():
        assert name.startswith("sec.") and t.label and (t.item or t.forms or t.tagged)


def test_feed_carries_event_types_and_filters_by_them(
    client, auth, db, sec_client, fake_sec, submissions_aapl
):
    ingest_company(db, sec_client, "320193")  # backfill: nothing on the feed
    _new_filing(fake_sec, submissions_aapl, "0000320193-26-000201", form="8-K", items="4.02,9.01")
    ingest_company(db, sec_client, "320193")

    def get(q):
        r = client.get("/v1/events?" + q + SINCE, headers=auth)
        assert r.status_code == 200, r.text
        return r.json()["data"]

    (ev,) = get("")
    assert ev["data"]["event_types"] == ["sec.restatement"]
    assert "4.02" in ev["data"]["event_labels"]["sec.restatement"]
    assert [e["data"]["accession_number"] for e in get("event_type=sec.restatement")] == [
        "0000320193-26-000201"
    ]
    assert get("event_type=sec.bankruptcy") == []
    assert len(get("event_type=sec.restatement,sec.bankruptcy&cik=320193")) == 1
    assert get("event_type=sec.officer_change") == []  # leadership only, none read here
    for bad in ("event_type=sec.nope", "event_type=sec.restatement,new_listing",
                "event_type=sec.restatement&mic=XPAR"):  # fmt: skip
        assert client.get("/v1/events?" + bad, headers=auth).status_code == 422, bad


def test_watch_limited_to_event_types_fires_only_for_them(
    client, auth, db, sec_client, fake_sec, submissions_aapl
):
    ingest_company(db, sec_client, "320193")
    hook = {"destination_type": "webhook", "destination": "https://example.com/hook"}
    r = client.post(
        "/v1/watches",
        json={"cik": "320193", **hook, "event_types": ["sec.bankruptcy", "sec.restatement"]},
        headers=auth,
    )
    assert r.status_code == 201, r.text
    assert r.json()["event_types"] == ["sec.bankruptcy", "sec.restatement"]
    everything = client.post(
        "/v1/watches", json={"cik": "320193", **hook, "destination": "https://example.org/h"},
        headers=auth,
    )  # fmt: skip
    assert everything.status_code == 201 and everything.json()["event_types"] is None
    bad = client.post(
        "/v1/watches", json={"cik": "320193", **hook, "event_types": ["sec.nope"]}, headers=auth
    )
    assert bad.status_code == 422

    _new_filing(fake_sec, submissions_aapl, "0000320193-26-000202", form="8-K", items="2.02")
    ingest_company(db, sec_client, "320193")
    assert len(db.scalars(select(NotificationDelivery)).all()) == 1  # only the unfiltered watch

    _new_filing(fake_sec, submissions_aapl, "0000320193-26-000203", form="8-K", items="4.02")
    ingest_company(db, sec_client, "320193")
    deliveries = db.scalars(select(NotificationDelivery)).all()
    assert len(deliveries) == 3  # both watches fire for the restatement
    d = deliveries[-1]
    from app.db.models import Filing

    payload = build_event_payload(d, db.get(Filing, d.filing_id), d.created_at)
    assert payload["data"]["event_types"] == ["sec.restatement"]
    assert payload["data"]["items"] == ["4.02"]


def test_a_watch_can_be_sent_a_signed_test_event(client, auth, db, sec_client, monkeypatch):
    from app.core.security import verify_webhook_signature
    from app.services import notifications

    ingest_company(db, sec_client, "320193")
    w = client.post("/v1/watches", json={"cik": "320193", "destination_type": "webhook",
                                          "destination": "https://hooks.example.com/t"},
                    headers=auth).json()  # fmt: skip
    sent = []

    class Resp:
        status_code = 200

    def fake_send(self, url, body, headers):
        sent.append((url, body, headers))
        return Resp()

    monkeypatch.setattr(notifications.WebhookSender, "send", fake_send)
    r = client.post(f"/v1/watches/{w['id']}/test", headers=auth)
    assert r.status_code == 200 and r.json()["delivered"] is True
    url, body, headers = sent[0]
    assert headers["X-Event-Type"] == "sec.test"
    assert verify_webhook_signature(w["webhook_secret"], headers["X-Signature-Timestamp"],
                                    headers["X-Signature"], body)  # fmt: skip
