from sqlalchemy import select

from app.db.models import ApiKey, KeyRequest


def _reset():
    from app.api import routes_key_requests

    routes_key_requests.ip_limiter.reset()


def test_request_key_records_and_dedupes(client, db):
    _reset()
    payload = {
        "email": "Dev@Example.com",
        "use_case": "Backtesting revenue growth for an internal tool",
        "website": "",
    }
    r = client.post("/v1/developer/key-requests", json=payload)
    assert r.status_code == 202, r.text
    body = r.json()
    assert (
        body["status"] == "pending" and body["email"] == "dev@example.com" and "request_id" in body
    )
    assert "api_key" not in r.text
    # duplicate pending request for the same email is acknowledged, not duplicated
    r2 = client.post("/v1/developer/key-requests", json=payload)
    assert r2.status_code == 202 and r2.json()["request_id"] == body["request_id"]
    assert db.scalar(select(KeyRequest.id)) is not None
    assert len(db.scalars(select(KeyRequest)).all()) == 1


def test_request_key_validation_and_honeypot(client):
    _reset()
    bad = [
        ({"email": "not-an-email", "use_case": "x" * 20}, 422),
        ({"email": "a@example.com", "use_case": "short"}, 422),
        (
            {"email": "a@example.com", "use_case": "x" * 20, "website": "http://spam.example"},
            202,
        ),  # honeypot: silently accepted
    ]
    for payload, status in bad:
        r = client.post("/v1/developer/key-requests", json=payload)
        assert r.status_code == status, (payload, r.text)


def test_honeypot_hits_are_not_stored(client, db):
    _reset()
    client.post(
        "/v1/developer/key-requests",
        json={"email": "bot@example.com", "use_case": "x" * 20, "website": "http://spam.example"},
    )
    assert db.scalars(select(KeyRequest)).all() == []


def test_request_key_rate_limited_per_ip(client, monkeypatch):
    from app.api import routes_key_requests

    _reset()
    monkeypatch.setattr(routes_key_requests, "KEY_REQUEST_RATE_LIMIT_PER_HOUR", 2)
    for i in range(2):
        assert (
            client.post(
                "/v1/developer/key-requests",
                json={"email": f"u{i}@example.com", "use_case": "x" * 20},
            ).status_code
            == 202
        )
    r = client.post(
        "/v1/developer/key-requests", json={"email": "u9@example.com", "use_case": "x" * 20}
    )
    assert r.status_code == 429 and "Retry-After" in r.headers
    _reset()


def test_approve_issues_key_once_and_marks_request(client, db, settings):
    from app.services.key_requests import approve_request, list_pending

    _reset()
    rid = client.post(
        "/v1/developer/key-requests", json={"email": "ok@example.com", "use_case": "x" * 20}
    ).json()["request_id"]
    pending = list_pending(db)
    assert [str(p.id) for p in pending] == [rid]
    key, raw = approve_request(db, settings, pending[0].id, plan="free", actor="test")
    db.commit()
    assert (
        raw.startswith("prv_test_") and key.owner_email == "ok@example.com" and key.plan == "free"
    )
    req = db.get(KeyRequest, pending[0].id)
    assert req.status == "approved" and req.approved_key_id == key.id and req.approved_at
    assert list_pending(db) == []
    # approving again is refused
    import pytest

    with pytest.raises(ValueError):
        approve_request(db, settings, pending[0].id, plan="free", actor="test")
    # the issued key works
    assert client.get("/v1/developer/usage", headers={"X-API-Key": raw}).status_code == 200
    assert db.scalar(select(ApiKey).where(ApiKey.id == key.id)) is not None


def test_reject_request(client, db, settings):
    from app.services.key_requests import list_pending, reject_request

    _reset()
    client.post(
        "/v1/developer/key-requests", json={"email": "no@example.com", "use_case": "x" * 20}
    )
    req = list_pending(db)[0]
    reject_request(db, req.id, reason="not a fit", actor="test")
    db.commit()
    assert db.get(KeyRequest, req.id).status == "rejected"
    # a new request after rejection is allowed
    assert (
        client.post(
            "/v1/developer/key-requests", json={"email": "no@example.com", "use_case": "x" * 20}
        ).status_code
        == 202
    )


def test_landing_page_has_request_form(client):
    html = client.get("/").text
    assert 'id="key-request-form"' in html and "/v1/developer/key-requests" in html


def test_openapi_marks_key_requests_public(client):
    spec = client.get("/openapi.json").json()
    assert spec["paths"]["/v1/developer/key-requests"]["post"]["security"] == []
