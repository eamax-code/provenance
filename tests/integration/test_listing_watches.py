"""Watches and webhooks for listing events (ticket 09)."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta

import httpx
from sqlalchemy import select

from app.core.security import verify_webhook_signature
from app.db.models import NotificationDelivery
from app.services.markets import ingest
from app.services.markets.records import ListingRecord
from app.services.notifications import WebhookSender, deliver_pending

HOOK = "https://hooks.example.com/listings"


def _venues(db):
    ingest.ensure_market(db, "XPAR", "Euronext Paris", "FR", "europe", "esma_firds", "x")
    ingest.ensure_market(db, "XLON", "London Stock Exchange", "GB", "uk", "fca_firds", "x")
    db.commit()


def _listing(db, isin, mic, name, days_ago=2, requested=None):
    return ingest.ingest_records(
        db,
        [
            ListingRecord(
                isin=isin,
                mic=mic,
                issuer_name=name,
                first_trade_date=date.today() - timedelta(days=days_ago),
                issuer_requested=requested,
                source="esma_firds" if mic != "XLON" else "fca_firds",
                source_url="x",
            )
        ],
        "esma_firds" if mic != "XLON" else "fca_firds",
        now=datetime.now(UTC),
    )


class NoDNS(WebhookSender):
    def send(self, url, body, headers):
        return self.http.post(url, content=body, headers=headers)


def test_watch_by_country_receives_signed_new_listing(client, auth, db, settings):
    _venues(db)
    r = client.post(
        "/v1/listing-watches",
        json={"scope_type": "country", "scope_value": "fr", "destination_type": "webhook",
              "destination": HOOK},
        headers=auth,
    )  # fmt: skip
    assert r.status_code == 201, r.text
    watch = r.json()
    assert watch["scope_value"] == "FR" and watch["event_types"] == [
        "new_listing",
        "delisting",
        "suspended",
    ]
    secret = watch["webhook_secret"]
    res = _listing(db, "FR001400AJ45", "XPAR", "EXOSENS", requested=True)
    assert res.deliveries_created == 1
    _listing(db, "GB00BNTJ3546", "XLON", "ALLFUNDS GROUP PLC")  # another country: no delivery
    assert db.scalar(
        select(NotificationDelivery.id).where(NotificationDelivery.listing_watch_id.is_not(None))
    )  # noqa: E501
    received = []

    def handler(request):
        received.append(request)
        return httpx.Response(204)

    sender = NoDNS(settings, http=httpx.Client(transport=httpx.MockTransport(handler)))
    counts = deliver_pending(db, settings, sender=sender)
    assert counts["delivered"] == 1 and len(received) == 1
    req = received[0]
    assert req.headers["X-Event-Type"] == "listing.new_listing"
    assert verify_webhook_signature(
        secret, req.headers["X-Signature-Timestamp"], req.headers["X-Signature"], req.content
    )
    data = json.loads(req.content)["data"]
    assert data["isin"] == "FR001400AJ45" and data["venue"] == "Euronext Paris"
    assert data["country"] == "FR" and data["details"]["likely_primary_listing"] is True
    assert "source_url" not in data  # register file links are never sent
    deliveries = client.get(f"/v1/listing-watches/{watch['id']}/deliveries", headers=auth).json()[
        "data"
    ]
    assert len(deliveries) == 1 and deliveries[0]["status"] == "delivered"
    # Re-ingesting the same record raises no new event and no second delivery.
    assert _listing(db, "FR001400AJ45", "XPAR", "EXOSENS", requested=True).deliveries_created == 0


def test_scope_and_event_type_filters(client, auth, db):
    _venues(db)

    def make(**body):
        base = {"destination_type": "webhook", "destination": HOOK}
        return client.post("/v1/listing-watches", json={**base, **body}, headers=auth)

    assert make(scope_type="mic", scope_value="xlon", event_types=["delisting"]).status_code == 201
    assert make(scope_type="region", scope_value="Europe").json()["scope_value"] == "europe"
    assert make(scope_type="mic", scope_value="XNYS").status_code == 422  # not covered
    assert make(scope_type="country", scope_value="US").status_code == 422
    assert make(scope_type="region", scope_value="asia").status_code == 422
    assert make(scope_type="mic", scope_value="XPAR", event_types=["merger"]).status_code == 422
    # The XLON watch wants delistings only; the europe watch takes the Paris listing.
    assert _listing(db, "GB00BNTJ3546", "XLON", "ALLFUNDS GROUP PLC").deliveries_created == 0
    assert _listing(db, "FR001400AJ45", "XPAR", "EXOSENS").deliveries_created == 1


def test_listing_watches_count_toward_the_plan_and_can_be_stopped(client, auth, db, settings):
    _venues(db)
    from app.core.config import plan_limits

    cap = plan_limits("free", settings)["max_active_watches"]
    body = {"scope_type": "region", "scope_value": "europe", "destination_type": "webhook",
            "destination": HOOK}  # fmt: skip
    ids = [
        client.post("/v1/listing-watches", json=body, headers=auth).json()["id"] for _ in range(cap)
    ]  # noqa: E501
    over = client.post("/v1/listing-watches", json=body, headers=auth)
    assert over.status_code == 422 and over.json()["error"]["code"] == "watch_limit_reached"
    stopped = client.delete(f"/v1/listing-watches/{ids[0]}", headers=auth).json()
    assert stopped["is_active"] is False
    assert len(client.get("/v1/listing-watches", headers=auth).json()["data"]) == cap - 1
    assert client.post("/v1/listing-watches", json=body, headers=auth).status_code == 201
    other = client.get(f"/v1/listing-watches/{ids[0]}/deliveries", headers={"X-API-Key": "nope"})
    assert other.status_code == 401
    # A stopped watch's pending deliveries fail rather than send.
    assert _listing(db, "FR001400AJ45", "XPAR", "EXOSENS").deliveries_created == cap
