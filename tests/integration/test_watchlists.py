"""X-07: watchlists stored per API key (docs/api-contracts-explorer.md)."""

from __future__ import annotations

import json

HOOK = "https://hooks.example.com/watchlist"


def _other_key(db, settings):
    from app.services.api_keys import create_key_record

    _, raw = create_key_record(db, settings, "other@example.com", "free", "other", actor="test")
    db.commit()
    return {"X-API-Key": raw}


def test_create_read_update_delete(client, auth, items_aapl):
    body = {"name": "Mine", "ciks": ["320193"], "columns": ["revenue", "operating_margin"]}
    r = client.post("/v1/watchlists", json=body, headers=auth)
    assert r.status_code == 201, r.text
    wl = r.json()
    assert wl["id"].startswith("wl_") and wl["ciks"] == ["0000320193"]
    assert client.get("/v1/watchlists", headers=auth).json()["data"][0]["id"] == wl["id"]
    up = client.patch(f"/v1/watchlists/{wl['id']}", json={"name": "Renamed", "ciks": []},
                      headers=auth).json()  # fmt: skip
    assert up["name"] == "Renamed" and up["ciks"] == []
    assert client.delete(f"/v1/watchlists/{wl['id']}", headers=auth).status_code == 204
    assert client.get(f"/v1/watchlists/{wl['id']}", headers=auth).status_code == 404


def test_another_keys_list_is_not_found(client, auth, db, settings, items_aapl):
    wl = client.post("/v1/watchlists", json={"name": "Private"}, headers=auth).json()
    other = _other_key(db, settings)
    r = client.get(f"/v1/watchlists/{wl['id']}", headers=other)
    assert r.status_code == 404 and r.json()["error"]["code"] == "watchlist_not_found"
    assert client.get("/v1/watchlists", headers=other).json()["data"] == []


def test_limits_come_from_the_plan(client, auth, items_aapl):
    from app.core.plans import PLANS

    free = PLANS["free"]
    assert (free.max_watchlists, free.max_watchlist_companies, free.max_watchlist_columns) == (
        3, 50, 8)  # fmt: skip
    assert all(PLANS[p].max_watchlists == 25 for p in ("analyst", "builder", "team", "enterprise"))
    for i in range(3):
        assert (
            client.post("/v1/watchlists", json={"name": f"L{i}"}, headers=auth).status_code == 201
        )
    r = client.post("/v1/watchlists", json={"name": "L4"}, headers=auth)
    assert r.status_code == 422 and r.json()["error"]["code"] == "watchlist_limit_reached"


def test_bad_companies_and_columns(client, auth, items_aapl):
    r = client.post("/v1/watchlists", json={"name": "x", "ciks": ["9999999"]}, headers=auth)
    assert r.status_code == 422 and "9999999" in r.json()["error"]["message"]
    r = client.post("/v1/watchlists", json={"name": "x", "columns": ["price"]}, headers=auth)
    assert r.status_code == 422 and "price" in r.json()["error"]["message"]
    many = {"name": "x", "ciks": [str(i) for i in range(1, 52)]}
    assert client.post("/v1/watchlists", json=many, headers=auth).status_code == 422
    cols = {
        "name": "x",
        "columns": [
            "revenue",
            "net_income",
            "total_assets",
            "operating_income",
            "operating_cash_flow",
            "capex",
            "sbc",
            "sga",
            "r_and_d",
        ],
    }
    assert client.post("/v1/watchlists", json=cols, headers=auth).status_code == 422


def test_rows_events_and_watch(client, auth, items_aapl):
    body = {
        "name": "Apple",
        "ciks": ["320193"],
        "columns": ["revenue", "operating_margin", "latest_filing", "reporting_currency"],
    }
    wl = client.post("/v1/watchlists", json=body, headers=auth).json()
    rows = client.get(f"/v1/watchlists/{wl['id']}/rows", headers=auth).json()
    cells = rows["data"][0]["cells"]
    assert cells["revenue"]["value"] == 391035000000 and cells["revenue"]["yoy"]["derived"]
    assert cells["revenue"]["source_url"].startswith("https://www.sec.gov/Archives/")
    assert cells["operating_margin"]["value"] == 31.5 and cells["operating_margin"]["derived"]
    assert cells["latest_filing"]["filing_url"].startswith("https://www.sec.gov/Archives/")
    ev = client.get(f"/v1/watchlists/{wl['id']}/events?types=filing&limit=5", headers=auth).json()
    assert ev["data"] and all(i["cik"] == "0000320193" and i["display_name"] for i in ev["data"])
    hook = {"destination_type": "webhook", "destination": HOOK}
    made = client.post(f"/v1/watchlists/{wl['id']}/watch", json=hook, headers=auth)
    assert made.status_code == 201, made.text
    watches = made.json()["watches"]
    assert len(watches) == 1 and watches[0]["webhook_secret"]
    assert any(
        w["cik"] == "0000320193" for w in client.get("/v1/watches", headers=auth).json()["data"]
    )
    text = json.dumps(rows)
    assert "first_detected" not in text and "data.sec.gov" not in text
