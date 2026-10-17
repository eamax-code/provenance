from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy import select

from app.core.security import derive_watch_secret, verify_webhook_signature
from app.db.models import CompanyWatch, Filing, NotificationDelivery
from app.services.ingestion import ingest_company
from app.services.notifications import (
    WebhookSender,
    backoff_seconds,
    create_deliveries_for_filing,
    deliver_pending,
    make_event_id,
)


def _watch(db, api_key_id, cik="0000320193", dest="https://hooks.example.com/sec", active=True):
    w = CompanyWatch(
        api_key_id=api_key_id,
        cik=cik,
        destination_type="webhook",
        destination=dest,
        is_active=active,
        created_at=datetime.now(UTC),
    )
    db.add(w)
    db.flush()
    return w


def _key_id(db, settings):
    from app.api.routes_developer import create_key_record

    key, _ = create_key_record(db, settings, "n@example.com", "free", None, actor="test")
    return key.id


class RecordingSender(WebhookSender):
    def __init__(self, settings, responses):
        super().__init__(settings, http=httpx.Client(transport=httpx.MockTransport(self._handle)))
        self.responses = list(responses)
        self.requests: list[httpx.Request] = []

    def send(self, url, body, headers):  # bypass DNS resolution in tests
        return self.http.post(url, content=body, headers=headers)

    def _handle(self, request):
        self.requests.append(request)
        r = self.responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return httpx.Response(r)


def test_event_id_is_stable():
    import uuid

    w = uuid.UUID(int=1)
    assert make_event_id(w, "0000320193", "0000320193-24-000123") == make_event_id(
        w, "0000320193", "0000320193-24-000123"
    )
    assert make_event_id(w, "0000320193", "0000320193-24-000123") != make_event_id(
        w, "0000320193", "0000320193-24-000124"
    )
    assert make_event_id(w, "0000320193", "x").startswith("evt_")


def test_one_delivery_per_active_watch_and_idempotent(db, sec_client, settings):
    ingest_company(db, sec_client, "320193")
    kid = _key_id(db, settings)
    _watch(db, kid)
    _watch(db, kid, dest="https://other.example.com/")
    _watch(db, kid, active=False)
    filing = db.scalar(select(Filing).where(Filing.accession_number == "0000320193-24-000123"))
    assert create_deliveries_for_filing(db, filing) == 2
    assert create_deliveries_for_filing(db, filing) == 0
    assert len(db.scalars(select(NotificationDelivery)).all()) == 2


def test_backfill_does_not_fan_out_but_new_filing_does(
    db, sec_client, settings, fake_sec, submissions_aapl
):
    # Watch created on a company known from the ticker file before first ingestion.
    from app.services.ingestion import import_ticker_mapping

    import_ticker_mapping(
        db, fake_sec.routes["https://www.sec.gov/files/company_tickers_exchange.json"][1]
    )
    kid = _key_id(db, settings)
    _watch(db, kid)
    db.commit()
    ingest_company(db, sec_client, "320193")
    assert db.scalars(select(NotificationDelivery)).all() == []
    recent = {k: list(v) for k, v in submissions_aapl["filings"]["recent"].items()}
    for col, val in [
        ("accessionNumber", "0000320193-25-000001"),
        ("filingDate", "2025-01-31"),
        ("reportDate", "2024-12-28"),
        ("acceptanceDateTime", "2025-01-31T06:00:00.000Z"),
        ("form", "10-Q"),
        ("primaryDocument", "x.htm"),
    ]:
        recent[col].insert(0, val)
    fake_sec.add(
        "https://data.sec.gov/submissions/CIK0000320193.json",
        {**submissions_aapl, "filings": {"recent": recent}},
    )
    result = ingest_company(db, sec_client, "320193")
    assert result.notifications_created == 1


def test_delivery_success_is_signed_and_verifiable(db, sec_client, settings):
    ingest_company(db, sec_client, "320193")
    kid = _key_id(db, settings)
    w = _watch(db, kid)
    filing = db.scalar(select(Filing).where(Filing.accession_number == "0000320193-24-000123"))
    create_deliveries_for_filing(db, filing)
    db.commit()
    sender = RecordingSender(settings, [200])
    counts = deliver_pending(db, settings, sender=sender)
    assert counts == {"attempted": 1, "delivered": 1, "retrying": 0, "failed": 0}
    req = sender.requests[0]
    secret = derive_watch_secret(settings.webhook_signing_secret, str(w.id))
    assert verify_webhook_signature(
        secret, req.headers["X-Signature-Timestamp"], req.headers["X-Signature"], req.content
    )
    import json

    payload = json.loads(req.content)
    assert (
        payload["event_type"] == "sec.filing.detected"
        and payload["data"]["accession_number"] == "0000320193-24-000123"
    )
    assert payload["data"]["source_url"].startswith(
        "https://www.sec.gov/Archives/edgar/data/320193/"
    )
    assert req.headers["X-Event-Id"] == payload["event_id"]
    d = db.scalar(select(NotificationDelivery))
    assert d.status == "delivered" and d.delivered_at is not None and d.last_status_code == 200
    assert db.get(CompanyWatch, w.id).last_delivered_at is not None
    # Re-running does nothing more
    assert deliver_pending(db, settings, sender=sender)["attempted"] == 0


def test_retry_then_fail_after_max_attempts(db, sec_client, settings):
    ingest_company(db, sec_client, "320193")
    kid = _key_id(db, settings)
    _watch(db, kid)
    filing = db.scalar(select(Filing).where(Filing.accession_number == "0000320193-24-000123"))
    create_deliveries_for_filing(db, filing)
    db.commit()
    sender = RecordingSender(settings, [503, httpx.ConnectTimeout("t"), 500])
    now = datetime.now(UTC)
    assert deliver_pending(db, settings, sender=sender, now=now)["retrying"] == 1
    d = db.scalar(select(NotificationDelivery))
    assert d.status == "retrying" and d.attempt_count == 1 and d.next_attempt_at > now
    # not due yet
    assert deliver_pending(db, settings, sender=sender, now=now)["attempted"] == 0
    later = now + timedelta(hours=2)
    assert deliver_pending(db, settings, sender=sender, now=later)["retrying"] == 1
    assert d.last_error_redacted == "timeout"
    much_later = later + timedelta(hours=2)
    counts = deliver_pending(db, settings, sender=sender, now=much_later)
    assert (
        counts["failed"] == 1 and d.status == "failed" and d.attempt_count == 3
    )  # settings max = 3
    assert len(sender.requests) == 3


def test_4xx_is_not_retried_and_redirect_fails(db, sec_client, settings):
    ingest_company(db, sec_client, "320193")
    kid = _key_id(db, settings)
    _watch(db, kid)
    _watch(db, kid, dest="https://redirect.example.com/")
    filing = db.scalar(select(Filing).where(Filing.accession_number == "0000320193-24-000123"))
    create_deliveries_for_filing(db, filing)
    db.commit()
    sender = RecordingSender(settings, [404, 302])
    counts = deliver_pending(db, settings, sender=sender)
    assert counts["failed"] == 2 and counts["retrying"] == 0
    statuses = sorted(d.last_status_code for d in db.scalars(select(NotificationDelivery)))
    assert statuses == [302, 404]


def test_deactivated_watch_blocks_pending_delivery(db, sec_client, settings):
    ingest_company(db, sec_client, "320193")
    kid = _key_id(db, settings)
    w = _watch(db, kid)
    filing = db.scalar(select(Filing).where(Filing.accession_number == "0000320193-24-000123"))
    create_deliveries_for_filing(db, filing)
    w.is_active = False
    db.commit()
    sender = RecordingSender(settings, [200])
    counts = deliver_pending(db, settings, sender=sender)
    assert counts["failed"] == 1 and sender.requests == []


def test_ssrf_rejection_at_delivery_time(db, sec_client, settings, monkeypatch):
    import socket

    ingest_company(db, sec_client, "320193")
    kid = _key_id(db, settings)
    _watch(db, kid, dest="https://rebind.example.com/hook")
    filing = db.scalar(select(Filing).where(Filing.accession_number == "0000320193-24-000123"))
    create_deliveries_for_filing(db, filing)
    db.commit()
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: [(2, 1, 6, "", ("127.0.0.1", 443))])
    sender = WebhookSender(
        settings, http=httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200)))
    )
    counts = deliver_pending(db, settings, sender=sender)
    d = db.scalar(select(NotificationDelivery))
    assert counts["failed"] == 1 and "destination rejected" in d.last_error_redacted


def test_backoff_is_bounded_and_jittered():
    assert 0.5 <= backoff_seconds(1, 1.0, rng=lambda: 0.0) <= 1.0
    assert backoff_seconds(3, 30.0, rng=lambda: 1.0) == 120.0
    assert backoff_seconds(50, 30.0, rng=lambda: 1.0) == 3600.0


def test_email_watch_without_config_fails_clearly(db, sec_client, settings):
    ingest_company(db, sec_client, "320193")
    kid = _key_id(db, settings)
    w = CompanyWatch(
        api_key_id=kid,
        cik="0000320193",
        destination_type="email",
        destination="a@example.com",
        is_active=True,
        created_at=datetime.now(UTC),
    )
    db.add(w)
    db.flush()
    filing = db.scalar(select(Filing).where(Filing.accession_number == "0000320193-24-000123"))
    create_deliveries_for_filing(db, filing)
    db.commit()
    counts = deliver_pending(db, settings, sender=RecordingSender(settings, []))
    d = db.scalar(select(NotificationDelivery))
    assert counts["failed"] == 1 and "not configured" in d.last_error_redacted
