"""D-L1 (2026-11-25): the demo key trims a large `limit` on every list endpoint, never refuses it.
A keyless phone reader's Connections list asked /insider-transactions?limit=20 and got a 403
demo_limit while search trimmed. Every GET endpoint in the OpenAPI spec that takes `limit` is
called here with the demo key, so a new endpoint cannot bring the refusal back."""

from __future__ import annotations

import pytest

DEMO = {"X-API-Key": "demo"}
CIK = "320193"
FILL = {"q": "apple", "metric": "revenue", "year": "2025"}
ROW_KEYS = ("data", "hits", "plans", "proposed_sales", "threads", "parents", "children",
            "subsidiaries")  # fmt: skip


@pytest.fixture(autouse=True)
def _reset_limits():
    from app.api import dependencies

    for limiter in (dependencies.demo_minute_limiter, dependencies.demo_day_limiter,
                    dependencies.demo_all_limiter):  # fmt: skip
        limiter.reset()
    yield


def _list_endpoints(client):
    spec = client.get("/openapi.json").json()
    for path, ops in spec["paths"].items():
        params = (ops.get("get") or {}).get("parameters", [])
        limit = next((p for p in params if p["name"] == "limit" and p["in"] == "query"), None)
        if limit is None:
            continue
        query = {p["name"]: FILL[p["name"]] for p in params
                 if p.get("required") and p["in"] == "query" and p["name"] in FILL}  # fmt: skip
        query["limit"] = min(50, limit["schema"].get("maximum") or 50)
        url = path.replace("{cik}", CIK).replace("{wid}", "1").replace("{watch_id}", "1")
        yield path, url, query


def test_every_list_endpoint_trims_a_large_limit_for_the_demo_key(client, ingested_aapl, settings):
    from app.api import dependencies

    cap, ok, seen = settings.demo_max_limit, 0, 0
    for path, url, query in _list_endpoints(client):
        seen += 1
        dependencies.demo_minute_limiter.reset()
        r = client.get(url, params=query, headers=DEMO)
        body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
        code = (body.get("error") or {}).get("code") if isinstance(body, dict) else None
        assert code != "demo_limit", f"{path} refused limit={query['limit']} for the demo key"
        if r.status_code != 200 or not isinstance(body, dict):
            continue
        ok += 1
        for k in ROW_KEYS:
            v = body.get(k)
            rows = v.get("data") if isinstance(v, dict) else v
            if isinstance(rows, list):
                assert len(rows) <= cap, f"{path}: {len(rows)} {k} for the demo key"
    assert seen >= 30 and ok >= 10  # the spec was read and most company lists answered


def test_a_trimmed_list_is_the_first_page_with_a_note(client, ingested_aapl, settings):
    r = client.get(f"/v1/companies/{CIK}/facts?period=all&limit=50", headers=DEMO)
    body = r.json()
    assert r.status_code == 200 and len(body["data"]) == settings.demo_max_limit
    assert body["meta"]["has_more"] is False and body["meta"].get("next_offset") is None
    assert any("at most" in n for n in body.get("notes", []))
