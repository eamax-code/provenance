"""D-03: derived figures at query time, never stored, each listing its inputs."""

from __future__ import annotations

from sqlalchemy import func, select

from app.db.models import FinancialFact
from app.services import ratios


def test_compute_rules():
    r = ratios.RATIOS
    assert ratios.compute(r["operating_margin"], 30.0, 120.0) == 25.0
    assert ratios.compute(r["free_cash_flow"], 100.0, 30.0) == 70.0
    assert ratios.compute(r["current_ratio"], 150.0, 100.0) == 1.5
    assert ratios.compute(r["net_margin"], 5.0, 0.0) is None  # no positive divisor
    assert ratios.compute(r["net_margin"], None, 10.0) is None
    assert ratios.unit_of(r["book_value_per_share"], "USD") == "USD/shares"
    assert not ratios.compatible(r["net_margin"], "TWD", "USD")  # never across currencies
    assert ratios.compatible(r["book_value_per_share"], "EUR", "shares")


def test_derived_metric_on_facts_and_screen(client, auth, db, ingested_aapl):
    stored = db.scalar(select(func.count()).where(FinancialFact.derived.is_(True)))
    r = client.get("/v1/companies/320193/facts?metric=operating_margin", headers=auth)
    assert r.status_code == 200, r.text
    rows = r.json()["data"]
    top = rows[0]
    assert top["metric"] == "operating_margin" and top["unit"] == "%" and top["derived"] is True
    assert top["quality_status"] == "derived" and top["period_label"] == "FY2024"
    assert 25 < float(top["value"]) < 40
    inputs = top["derivation"]["inputs"]
    assert [i["metric"] for i in inputs] == ["operating_income", "revenue"]
    assert all(i["source_url"].startswith("https://www.sec.gov/") for i in inputs)
    assert "derived by this service" in r.json()["notes"][0]
    bad = client.get("/v1/companies/320193/facts?metric=pe_ratio", headers=auth)
    assert bad.status_code == 422 and "operating_margin" in bad.json()["error"]["message"]

    s = client.get("/v1/facts/screen?metric=operating_margin&year=2024", headers=auth)
    assert s.status_code == 200, s.text
    body = s.json()
    assert body["unit"] == "%" and body["data"][0]["derived"] is True
    assert body["data"][0]["cik"] == "0000320193" and body["data"][0]["derivation"]["formula"]
    # never stored
    assert db.scalar(select(func.count()).where(FinancialFact.derived.is_(True))) == stored
