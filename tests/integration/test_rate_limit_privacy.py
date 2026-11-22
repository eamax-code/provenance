"""Rate-limit counters never hold an IP or email address: callers are keyed on a salted hash."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core import rate_limits
from app.core.rate_limits import holds_raw_identifier, purge_raw_identifiers
from app.db.models import RateLimitCounter

SITE = {"Origin": "http://testserver"}
PEERS = ["203.0.113.7", "2001:db8::42"]


@pytest.fixture
def db_store():
    rate_limits.configure("database")
    yield
    rate_limits.configure("auto")


def test_the_detector():
    assert holds_raw_identifier("demo-minute:demo-min:203.0.113.7")
    assert holds_raw_identifier("public-minute:public:2001:db8::42")
    assert holds_raw_identifier("public-minute:public:::ffff:203.0.113.7")
    assert holds_raw_identifier("email-hour:sign-in-email:dev@example.com")
    assert not holds_raw_identifier("demo-minute:demo-min:" + "a3" * 16)
    assert not holds_raw_identifier("key-minute:597a1d98-5155-483c-a01c-cd6774ff9f50")
    assert not holds_raw_identifier("demo-all:demo-all")


def test_no_counter_key_holds_an_address(app, db, db_store, ingested_aapl, settings, monkeypatch):
    from app.api import routes_account

    monkeypatch.setattr(settings, "email_provider", "console")
    monkeypatch.setattr(routes_account, "send_sign_in_email", lambda *a, **k: None)
    for peer in PEERS:
        with TestClient(app, client=(peer, 50000)) as c:
            assert c.get("/v1/companies/320193?api_key=demo").status_code == 200
            assert c.get("/v1/public/companies").status_code == 200
            assert c.get("/v1/stats").status_code == 200
            c.post("/v1/chat?api_key=demo", json={"message": "Apple revenue"})
            c.post(
                "/v1/developer/key-requests",
                json={"email": "dev@example.com", "use_case": "x" * 20, "website": ""},
            )
            c.post("/v1/account/sign-in", json={"email": "dev@example.com"}, headers=SITE)
    keys = set(db.scalars(select(RateLimitCounter.key)))
    prefixes = {k.split(":")[1] for k in keys}
    # every keyless counter was written, so the check below covers each of them
    assert {"demo-min", "demo-day", "demo-all", "public", "ip", "chat", "chat-day", "keyreq",
            "sign-in-ip", "sign-in-email"} <= prefixes, prefixes  # fmt: skip
    leaked = sorted(k for k in keys if holds_raw_identifier(k))
    assert leaked == [], leaked


def test_purge_removes_only_rows_with_an_address(engine, db, db_store):
    db.add_all(
        [
            RateLimitCounter(key="stats-minute:ip:203.0.113.7", window_start=1, count=3),
            RateLimitCounter(key="public-minute:public:2001:db8::42", window_start=1, count=1),
            RateLimitCounter(key="email-hour:sign-in-email:a@b.co", window_start=1, count=1),
            RateLimitCounter(key="stats-minute:ip:" + "0f" * 16, window_start=1, count=2),
            RateLimitCounter(key="key-minute:k1", window_start=1, count=9),
        ]
    )
    db.commit()
    assert purge_raw_identifiers(engine) == 3
    db.expire_all()
    left = sorted(db.scalars(select(RateLimitCounter.key)))
    assert left == ["key-minute:k1", "stats-minute:ip:" + "0f" * 16]
