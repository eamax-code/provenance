import csv
import io
import json

from sqlalchemy import select

from app.db.models import ApiUsage, AuditEvent


def test_admin_key_creation_and_revocation_flow(client, settings):
    r = client.post("/v1/developer/api-keys", json={"owner_email": "a@example.com"})
    assert r.status_code == 403
    r = client.post(
        "/v1/developer/api-keys",
        json={"owner_email": "a@example.com", "plan": "builder", "label": "x"},
        headers={"X-Admin-Token": settings.admin_token},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    raw = body["api_key"]
    assert (
        raw.startswith("prv_test_") and body["plan"] == "builder" and body["key_prefix"] == raw[:17]
    )
    auth = {"X-API-Key": raw}
    r = client.get("/v1/developer/api-keys", headers=auth)
    assert (
        r.status_code == 200
        and r.json()["data"][0]["id"] == body["id"]
        and "api_key" not in r.json()["data"][0]
    )
    r = client.delete(f"/v1/developer/api-keys/{body['id']}", headers=auth)
    assert r.status_code == 200 and r.json()["is_active"] is False and r.json()["revoked_at"]
    # immediate block
    r = client.get("/v1/developer/api-keys", headers=auth)
    assert r.status_code == 401 and r.json()["error"]["code"] == "invalid_api_key"


def test_admin_endpoint_disabled_without_token(client, settings, monkeypatch):
    monkeypatch.setattr(settings, "admin_token", "")
    r = client.post(
        "/v1/developer/api-keys",
        json={"owner_email": "a@example.com"},
        headers={"X-Admin-Token": "x"},
    )
    assert r.status_code == 503 and r.json()["error"]["code"] == "admin_endpoint_disabled"


def test_cannot_revoke_someone_elses_key(client, settings, auth):
    r = client.post(
        "/v1/developer/api-keys",
        json={"owner_email": "other@example.com"},
        headers={"X-Admin-Token": settings.admin_token},
    )
    other_id = r.json()["id"]
    assert client.delete(f"/v1/developer/api-keys/{other_id}", headers=auth).status_code == 404


def test_usage_metering_and_summary(client, auth, ingested_aapl, db):
    assert client.get("/v1/companies/search?q=aapl", headers=auth).status_code == 200
    assert client.get("/v1/companies/320193/facts?metric=bogus", headers=auth).status_code == 422
    assert (
        client.get("/v1/companies/1", headers={"X-API-Key": "bad"}).status_code == 401
    )  # not metered
    r = client.get("/v1/developer/usage", headers=auth)
    assert r.status_code == 200, r.text
    body = r.json()
    assert (
        body["total_requests"] == 2
        and body["successful_requests"] == 1
        and body["error_requests"] == 1
    )
    assert body["requests_by_route"] == {"/v1/companies/search": 1, "/v1/companies/{cik}/facts": 1}
    assert body["plan"]["plan"] == "free" and body["plan"]["monthly_requests_used"] == 2
    assert body["plan"]["rate_limit_per_minute"] == 60 and body["plan"]["max_export_rows"] == 1000
    assert "from" in body and "to" in body
    rows = db.scalars(select(ApiUsage)).all()
    assert all(r.request_id.startswith("req_") for r in rows)
    assert (
        client.get(
            "/v1/developer/usage?from=2026-02-01T00:00:00Z&to=2026-01-01T00:00:00Z", headers=auth
        ).status_code
        == 422
    )


def test_rate_limit_returns_429_with_retry_after(client, auth, monkeypatch):
    from app.api import dependencies

    monkeypatch.setitem(
        dependencies.plan_limits.__globals__["PLAN_LIMITS"],
        "free",
        {"rate_limit_per_minute": 2, "monthly_request_quota": 1000, "max_export_rows": 10},
    )
    monkeypatch.setattr(
        dependencies,
        "plan_limits",
        lambda plan, s: {
            "rate_limit_per_minute": 2,
            "monthly_request_quota": 1000,
            "max_export_rows": 10,
        },
    )
    assert client.get("/v1/companies/search?q=x", headers=auth).status_code == 200
    assert client.get("/v1/companies/search?q=x", headers=auth).status_code == 200
    r = client.get("/v1/companies/search?q=x", headers=auth)
    assert (
        r.status_code == 429
        and r.json()["error"]["code"] == "rate_limited"
        and int(r.headers["Retry-After"]) >= 1
    )


def test_monthly_quota_enforced(client, auth, monkeypatch):
    from app.api import dependencies

    monkeypatch.setattr(
        dependencies,
        "plan_limits",
        lambda plan, s: {
            "rate_limit_per_minute": 100,
            "monthly_request_quota": 1,
            "max_export_rows": 10,
        },
    )
    assert client.get("/v1/companies/search?q=x", headers=auth).status_code == 200
    r = client.get("/v1/companies/search?q=x", headers=auth)
    assert (
        r.status_code == 429
        and r.json()["error"]["code"] == "quota_exceeded"
        and "Retry-After" in r.headers
    )


def test_watch_lifecycle_scoped_to_caller(client, auth, settings, ingested_aapl, db):
    r = client.post(
        "/v1/watches",
        json={
            "cik": "320193",
            "destination_type": "webhook",
            "destination": "https://hooks.example.com/sec",
        },
        headers=auth,
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["is_active"] and body["cik"] == "0000320193" and len(body["webhook_secret"]) == 64
    watch_id = body["id"]
    r = client.get("/v1/watches", headers=auth)
    assert [w["id"] for w in r.json()["data"]] == [watch_id] and "webhook_secret" not in r.json()[
        "data"
    ][0]
    # another key sees nothing and cannot delete
    other = client.post(
        "/v1/developer/api-keys",
        json={"owner_email": "o@example.com"},
        headers={"X-Admin-Token": settings.admin_token},
    ).json()["api_key"]
    assert client.get("/v1/watches", headers={"X-API-Key": other}).json()["data"] == []
    assert client.delete(f"/v1/watches/{watch_id}", headers={"X-API-Key": other}).status_code == 404
    r = client.delete(f"/v1/watches/{watch_id}", headers=auth)
    assert r.status_code == 200 and r.json()["is_active"] is False and r.json()["deactivated_at"]
    assert client.get("/v1/watches", headers=auth).json()["data"] == []
    assert len(client.get("/v1/watches?include_inactive=true", headers=auth).json()["data"]) == 1
    assert client.get(f"/v1/watches/{watch_id}/deliveries", headers=auth).json()["data"] == []
    actions = {a.action for a in db.scalars(select(AuditEvent))}
    assert {"watch.created", "watch.deactivated", "api_key.created"} <= actions


def test_watch_validation(client, auth, ingested_aapl):
    bad = [
        (
            {"cik": "320193", "destination_type": "webhook", "destination": "http://example.com/"},
            "invalid_destination",
        ),
        (
            {"cik": "320193", "destination_type": "webhook", "destination": "https://127.0.0.1/"},
            "invalid_destination",
        ),
        (
            {
                "cik": "320193",
                "destination_type": "webhook",
                "destination": "https://169.254.169.254/",
            },
            "invalid_destination",
        ),
        (
            {"cik": "320193", "destination_type": "email", "destination": "a@example.com"},
            "email_delivery_not_configured",
        ),
        (
            {"cik": "1", "destination_type": "webhook", "destination": "https://example.com/"},
            "company_not_found",
        ),
        (
            {"cik": "zzz", "destination_type": "webhook", "destination": "https://example.com/"},
            "invalid_parameter",
        ),
        (
            {"cik": "320193", "destination_type": "pigeon", "destination": "https://example.com/"},
            "invalid_parameter",
        ),
    ]
    for payload, code in bad:
        r = client.post("/v1/watches", json=payload, headers=auth)
        assert r.status_code in (404, 422) and r.json()["error"]["code"] == code, (payload, r.text)


def test_new_filing_creates_delivery_and_webhook_is_verifiable(
    client, auth, settings, ingested_aapl, db, sec_client, fake_sec, submissions_aapl
):
    import httpx

    from app.core.security import verify_webhook_signature
    from app.services.ingestion import ingest_company
    from app.services.notifications import WebhookSender, deliver_pending

    secret = client.post(
        "/v1/watches",
        json={
            "cik": "320193",
            "destination_type": "webhook",
            "destination": "https://hooks.example.com/sec",
        },
        headers=auth,
    ).json()["webhook_secret"]
    watch_id = client.get("/v1/watches", headers=auth).json()["data"][0]["id"]
    recent = {k: list(v) for k, v in submissions_aapl["filings"]["recent"].items()}
    for col, val in [
        ("accessionNumber", "0000320193-25-000001"),
        ("filingDate", "2026-10-15"),
        ("reportDate", "2024-12-28"),
        ("acceptanceDateTime", "2026-10-15T06:00:00.000Z"),
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

    received = []

    def handler(request):
        received.append(request)
        return httpx.Response(200)

    class NoDNS(WebhookSender):
        def send(self, url, body, headers):
            return self.http.post(url, content=body, headers=headers)

    deliver_pending(
        db,
        settings,
        sender=NoDNS(settings, http=httpx.Client(transport=httpx.MockTransport(handler))),
    )
    req = received[0]
    assert verify_webhook_signature(
        secret, req.headers["X-Signature-Timestamp"], req.headers["X-Signature"], req.content
    )
    assert json.loads(req.content)["data"]["accession_number"] == "0000320193-25-000001"
    deliveries = client.get(f"/v1/watches/{watch_id}/deliveries", headers=auth).json()["data"]
    assert (
        len(deliveries) == 1
        and deliveries[0]["status"] == "delivered"
        and deliveries[0]["attempt_count"] == 1
    )
    # second ingestion of same payload creates no duplicate event
    assert ingest_company(db, sec_client, "320193").notifications_created == 0


def test_export_csv_and_json_with_limits(client, auth, ingested_aapl, db):
    r = client.get("/v1/exports/facts?metric=revenue&ciks=320193&format=csv", headers=auth)
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("text/csv")
    assert r.headers["content-disposition"].startswith('attachment; filename="facts_revenue_ciks1_')
    rows = list(csv.DictReader(io.StringIO(r.content.decode("utf-8"))))
    assert len(rows) == int(r.headers["X-Export-Rows"]) > 0
    for col in (
        "cik",
        "metric",
        "value",
        "unit",
        "currency",
        "period_start",
        "period_end",
        "period_type",
        "form_type",
        "filed_date",
        "accession_number",
        "source_tag",
        "source_url",
        "mapping_version",
        "quality_status",
        "first_detected_at",
        "processed_at",
    ):
        assert col in rows[0]
    assert all(row["source_url"].startswith("https://www.sec.gov/") for row in rows)
    assert all(
        row["quality_status"] in ("ok", "partial") for row in rows
    )  # ambiguous excluded by default

    r = client.get("/v1/exports/facts?metric=revenue&format=json&limit=2", headers=auth)
    body = r.json()
    assert (
        len(body["data"]) == 2
        and body["meta"]["truncated"] is True
        and r.headers["X-Export-Truncated"] == "true"
    )
    assert body["meta"]["mapping_version"] == "1.0.0"

    r = client.get("/v1/exports/facts?metric=revenue&limit=1001", headers=auth)
    assert r.status_code == 413 and r.json()["error"]["code"] == "export_limit_exceeded"
    r = client.get("/v1/exports/facts?format=csv", headers=auth)
    assert r.status_code == 422 and "full-universe" in r.json()["error"]["message"]
    assert (
        client.get("/v1/exports/facts?metric=revenue&format=xml", headers=auth).status_code == 422
    )
    assert (
        client.get(
            "/v1/exports/facts?ciks=" + ",".join(str(i) for i in range(1, 60)), headers=auth
        ).status_code
        == 422
    )
    assert client.get("/v1/exports/facts?metric=revenue").status_code == 401

    usage = client.get("/v1/developer/usage", headers=auth).json()
    assert usage["export_rows"] == len(rows) + 2 and usage["export_bytes"] > 0
    metered = db.scalars(select(ApiUsage).where(ApiUsage.export_rows.is_not(None))).all()
    assert len(metered) == 2


def test_export_include_ambiguous(client, auth, ingested_aapl):
    r = client.get(
        "/v1/exports/facts?metric=revenue&format=json&include_ambiguous=true", headers=auth
    )
    assert any(row["quality_status"] == "ambiguous_mapping" for row in r.json()["data"])


def test_openapi_documents_all_public_endpoints(client):
    r = client.get("/openapi.json")
    assert r.status_code == 200
    spec = r.json()
    paths = spec["paths"]
    expected = {
        ("/v1/companies/search", "get"),
        ("/v1/companies/{cik}", "get"),
        ("/v1/companies/{cik}/filings", "get"),
        ("/v1/companies/{cik}/facts", "get"),
        ("/v1/companies/{cik}/freshness", "get"),
        ("/v1/watches", "post"),
        ("/v1/watches", "get"),
        ("/v1/watches/{watch_id}", "delete"),
        ("/v1/watches/{watch_id}/deliveries", "get"),
        ("/v1/developer/api-keys", "post"),
        ("/v1/developer/api-keys", "get"),
        ("/v1/developer/api-keys/{key_id}", "delete"),
        ("/v1/developer/usage", "get"),
        ("/v1/exports/facts", "get"),
        ("/healthz", "get"),
        ("/readyz", "get"),
    }
    for path, method in expected:
        assert method in paths[path], (path, method)
    assert spec["components"]["securitySchemes"]["ApiKeyAuth"] == {
        "type": "apiKey",
        "in": "header",
        "name": "X-API-Key",
    }
    assert paths["/v1/companies/search"]["get"]["security"] == [{"ApiKeyAuth": []}]
    assert paths["/v1/developer/api-keys"]["post"]["security"] == [{"AdminToken": []}]
    assert (
        "401" in paths["/v1/companies/search"]["get"]["responses"]
        and "422" in paths["/v1/companies/search"]["get"]["responses"]
    )
    assert "ErrorEnvelope" in spec["components"]["schemas"]
    assert "not affiliated" in spec["info"]["description"]
    assert client.get("/docs").status_code == 200


def test_error_envelope_hides_internals(app, auth, monkeypatch):
    from fastapi.testclient import TestClient

    from app.api import routes_companies

    def boom(*a, **k):
        raise RuntimeError("secret sql detail")

    monkeypatch.setattr(routes_companies, "search_companies", boom)
    client = TestClient(app, raise_server_exceptions=False)
    r = client.get("/v1/companies/search?q=x", headers=auth)
    assert r.status_code == 500
    body = r.json()["error"]
    assert body["code"] == "internal_error" and body["message"] == "An internal error occurred."
    assert "secret" not in r.text and body["request_id"].startswith("req_")


def test_watch_limit_enforced_per_plan(
    client, auth, settings, ingested_aapl, db, monkeypatch, tickers_payload
):
    from app.api import routes_developer, routes_notifications
    from app.services.ingestion import import_ticker_mapping

    import_ticker_mapping(db, tickers_payload)
    db.commit()
    limits = {
        "rate_limit_per_minute": 100,
        "monthly_request_quota": 10_000,
        "max_export_rows": 10,
        "max_watches": 1,
        "max_active_watches": 2,
    }
    monkeypatch.setattr(routes_notifications, "plan_limits", lambda plan, s: limits)
    monkeypatch.setattr(routes_developer, "plan_limits", lambda plan, s: limits)
    body = {"destination_type": "webhook", "destination": "https://hooks.example.com/sec"}
    assert (
        client.post("/v1/watches", json={**body, "cik": "320193"}, headers=auth).status_code == 201
    )
    # same CIK again does not consume another slot
    assert (
        client.post(
            "/v1/watches",
            json={**body, "cik": "320193", "destination": "https://hooks.example.com/other"},
            headers=auth,
        ).status_code
        == 201
    )
    r = client.post("/v1/watches", json={**body, "cik": "789019"}, headers=auth)
    assert r.status_code == 422 and r.json()["error"]["code"] == "watch_limit_reached"
    # total active watch rows are capped too (same CIK, third destination)
    r = client.post(
        "/v1/watches",
        json={**body, "cik": "320193", "destination": "https://hooks.example.com/third"},
        headers=auth,
    )
    assert r.status_code == 422 and "active watches in total" in r.json()["error"]["message"]
    usage = client.get("/v1/developer/usage", headers=auth).json()
    assert usage["plan"]["max_watches"] == 1 and usage["plan"]["watched_companies_used"] == 1
    assert usage["plan"]["max_active_watches"] == 2 and usage["plan"]["active_watches_used"] == 2


def test_admin_can_create_builder_and_team_keys(client, settings):
    for plan in ("builder", "team", "enterprise"):
        r = client.post(
            "/v1/developer/api-keys",
            json={"owner_email": f"{plan}@example.com", "plan": plan},
            headers={"X-Admin-Token": settings.admin_token},
        )
        assert r.status_code == 201, r.text
        assert r.json()["plan"] == plan
    r = client.post(
        "/v1/developer/api-keys",
        json={"owner_email": "x@example.com", "plan": "platinum"},
        headers={"X-Admin-Token": settings.admin_token},
    )
    assert r.status_code == 422
