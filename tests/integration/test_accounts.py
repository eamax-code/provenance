"""Accounts: sign in by emailed link, a session cookie, keys, usage and theme (GH #15)."""

from __future__ import annotations

import re
from datetime import timedelta

import pytest

SITE = {"Origin": "http://testserver"}


@pytest.fixture
def outbox(settings, monkeypatch):
    """Capture sign-in emails instead of sending them."""
    sent: list[dict] = []
    from app.api import routes_account

    monkeypatch.setattr(settings, "email_provider", "console")
    monkeypatch.setattr(
        routes_account,
        "send_sign_in_email",
        lambda s, to, link, minutes: sent.append({"to": to, "link": link, "minutes": minutes}),
    )
    return sent


def token_from(mail: dict) -> str:
    return re.search(r"#token=([A-Za-z0-9_-]+)$", mail["link"]).group(1)


def sign_in(client, outbox, email="Dev@Example.com"):
    r = client.post("/v1/account/sign-in", json={"email": email}, headers=SITE)
    assert r.status_code == 202, r.text
    r = client.post("/v1/account/verify", json={"token": token_from(outbox[-1])}, headers=SITE)
    assert r.status_code == 200, r.text
    return r


def test_sign_up_and_sign_in_answer_the_same_and_create_the_account_on_first_link(client, outbox):
    new = client.post("/v1/account/sign-in", json={"email": "new@example.com"}, headers=SITE)
    sign_in(client, outbox, "old@example.com")
    client.cookies.clear()
    old = client.post("/v1/account/sign-in", json={"email": "old@example.com"}, headers=SITE)
    assert new.status_code == old.status_code == 202 and new.json() == old.json()  # no enumeration
    mail = outbox[0]
    assert mail["to"] == "new@example.com" and mail["minutes"] == 15
    assert mail["link"].startswith("http://testserver/account/verify/#token=")
    assert client.get("/v1/account").status_code == 401  # a link alone does not sign you in


def test_verify_sets_a_safe_session_cookie_and_the_link_works_once(client, outbox, db):
    r = sign_in(client, outbox)
    cookie = r.headers["set-cookie"]
    assert "prv_session=" in cookie and "HttpOnly" in cookie and "SameSite=lax" in cookie
    assert r.json()["email"] == "dev@example.com"  # stored in lower case
    again = client.post("/v1/account/verify", json={"token": token_from(outbox[-1])}, headers=SITE)
    assert again.status_code == 401 and again.json()["error"]["code"] == "invalid_link"
    from sqlalchemy import select

    from app.db.models import AccountSession, SignInToken

    stored = db.scalars(select(SignInToken.token_hash)).all()
    assert token_from(outbox[-1]) not in stored  # only hashes are kept
    raw_cookie = client.cookies.get("prv_session")
    assert raw_cookie not in db.scalars(select(AccountSession.token_hash)).all()


def test_an_expired_link_is_refused(client, outbox, db):
    from sqlalchemy import update

    from app.db.models import SignInToken, utcnow

    client.post("/v1/account/sign-in", json={"email": "late@example.com"}, headers=SITE)
    db.execute(update(SignInToken).values(expires_at=utcnow() - timedelta(seconds=1)))
    db.commit()
    r = client.post("/v1/account/verify", json={"token": token_from(outbox[-1])}, headers=SITE)
    assert r.status_code == 401


def test_operator_issued_keys_are_claimed_by_email_and_usage_is_shown(client, outbox, auth):
    client.get("/v1/companies/search?q=apple", headers=auth)  # one metered request
    body = sign_in(client, outbox, "DEV@example.com").json()  # the api_key fixture's owner
    assert [k["label"] for k in body["keys"]] == ["test"] and body["plan"] == "free"
    assert body["requests_this_month"] >= 1 and body["monthly_request_quota"] > 0
    assert "key_hash" not in str(body) and "api_key" not in body["keys"][0]


def test_create_name_and_revoke_keys(client, outbox):
    sign_in(client, outbox)
    r = client.post("/v1/account/keys", json={"label": "notebook"}, headers=SITE)
    assert r.status_code == 201 and r.json()["api_key"].startswith("prv_")
    raw, key_id = r.json()["api_key"], r.json()["id"]
    assert client.get("/v1/companies/search?q=a", headers={"X-API-Key": raw}).status_code == 200
    listed = client.get("/v1/account").json()["keys"]
    assert listed[0]["label"] == "notebook" and "api_key" not in listed[0]
    assert client.delete(f"/v1/account/keys/{key_id}", headers=SITE).json()["is_active"] is False
    assert client.get("/v1/companies/search?q=a", headers={"X-API-Key": raw}).status_code == 401


def test_key_limit_and_other_peoples_keys(client, outbox, settings, monkeypatch, db):
    from app.services.api_keys import create_key_record

    other, _ = create_key_record(db, settings, "someone@else.com", "team", None, actor="t")
    db.commit()
    monkeypatch.setattr(settings, "account_max_active_keys", 1)
    sign_in(client, outbox)
    assert client.post("/v1/account/keys", json={}, headers=SITE).status_code == 201
    r = client.post("/v1/account/keys", json={}, headers=SITE)
    assert r.status_code == 422 and r.json()["error"]["code"] == "key_limit_reached"
    assert client.delete(f"/v1/account/keys/{other.id}", headers=SITE).status_code == 404


def test_theme_follows_the_account_to_its_keys(client, outbox, auth):
    sign_in(client, outbox)
    r = client.patch("/v1/account", json={"ui_theme": "ledger"}, headers=SITE)
    assert r.status_code == 200 and r.json()["ui_theme"] == "ledger"
    assert client.get("/v1/developer/profile", headers=auth).json()["ui_theme"] == "ledger"
    assert client.patch("/v1/account", json={"ui_theme": "neon"}, headers=SITE).status_code == 422


def test_sign_out_and_sign_out_everywhere(client, outbox, app):
    from fastapi.testclient import TestClient

    sign_in(client, outbox)
    other = TestClient(app)
    other.post("/v1/account/sign-in", json={"email": "dev@example.com"}, headers=SITE)
    other.post("/v1/account/verify", json={"token": token_from(outbox[-1])}, headers=SITE)
    assert other.get("/v1/account").status_code == 200
    assert client.post("/v1/account/sign-out-everywhere", headers=SITE).status_code == 204
    assert (
        other.get("/v1/account").status_code == 401 and client.get("/v1/account").status_code == 401
    )
    sign_in(client, outbox)
    assert client.post("/v1/account/sign-out", headers=SITE).status_code == 204
    assert client.get("/v1/account").status_code == 401


def test_changes_from_another_site_are_refused(client, outbox):
    sign_in(client, outbox)
    evil = {"Origin": "https://evil.example"}
    assert client.post("/v1/account/keys", json={}, headers=evil).status_code == 403
    assert client.post("/v1/account/sign-out-everywhere", headers=evil).status_code == 403
    assert client.get("/v1/account").status_code == 200  # still signed in


def test_sign_in_is_rate_limited_per_address_and_quietly_per_email(client, outbox, settings,
                                                                   monkeypatch):  # fmt: skip
    monkeypatch.setattr(settings, "sign_in_per_email_per_hour", 2)
    for _ in range(4):
        r = client.post("/v1/account/sign-in", json={"email": "a@example.com"}, headers=SITE)
        assert r.status_code == 202  # the same answer, but no more mail
    assert len(outbox) == 2
    monkeypatch.setattr(settings, "sign_in_per_ip_per_hour", 4)
    r = client.post("/v1/account/sign-in", json={"email": "b@example.com"}, headers=SITE)
    assert r.status_code == 429


def test_without_email_delivery_sign_in_says_so(client, settings, monkeypatch):
    monkeypatch.setattr(settings, "email_provider", "none")
    r = client.post("/v1/account/sign-in", json={"email": "x@example.com"}, headers=SITE)
    assert r.status_code == 503 and r.json()["error"]["code"] == "email_delivery_not_configured"
    monkeypatch.setattr(settings, "email_provider", "console")
    monkeypatch.setattr(settings, "app_env", "production")
    r = client.post("/v1/account/sign-in", json={"email": "x@example.com"}, headers=SITE)
    assert r.status_code == 503  # the console never stands in for email in production
    assert client.post("/v1/account/sign-in", json={"email": "not-an-email"}).status_code == 422


def test_account_pages_are_served_in_the_shared_layout(client):
    html = client.get("/account/").text
    assert (
        'class="site-bar"' in html and "/account/account.js" in html and 'id="signin-form"' in html
    )
    verify = client.get("/account/verify/").text
    assert "/account/verify.js" in verify and 'content="noindex"' in verify
    js = client.get("/account/verify.js").text
    assert "location.hash" in js and "replaceState" in js and "method: 'POST'" in js
    header = client.get("/").text
    assert 'class="site-button" href="/account/">Get API key' in header
    spec = client.get("/openapi.json").json()["paths"]
    assert spec["/v1/account/sign-in"]["post"]["security"] == []
