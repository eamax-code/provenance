"""The screen and search show display_name, and the screen lists a predecessor registrant's
figure under its current successor (K-05, as the overview), 2026-11-23."""

from __future__ import annotations

from datetime import UTC, date, datetime

from app.db.models import Company, RegistrantSuccession
from app.services.intel import display_name

APPLE = "0000320193"
HOLDCO = "0002999999"


def _year(client, auth) -> int:
    facts = client.get(f"/v1/companies/{APPLE}/facts?metric=revenue&period=annual&limit=1",
                       headers=auth).json()["data"]  # fmt: skip
    return int(facts[0]["period_end"][:4])


def _successor(db) -> None:
    db.add(Company(cik=HOLDCO, legal_name="APPLE HOLDINGS EXAMPLE INC", ticker="AAPH",
                   registrant_name="Apple Holdings Example Inc.", source_url="https://www.sec.gov/",
                   first_detected_at=datetime.now(UTC), quality_status="ok"))  # fmt: skip
    db.add(RegistrantSuccession(
        predecessor_cik=APPLE, successor_cik=HOLDCO, effective_date=date(2026, 7, 1),
        evidence_accession="0002999999-26-000001", evidence_form="8-K12B",
        match_method="holding_company_reorganization", confidence="high",
    ))  # fmt: skip
    db.commit()


def test_screen_and_search_rows_carry_display_name(client, auth, db, ingested_aapl):
    c = db.query(Company).filter(Company.cik == APPLE).one()
    want = display_name(c.legal_name, c.ticker, c.registrant_name)
    year = _year(client, auth)
    for metric in ("revenue", "operating_margin"):
        rows = client.get(f"/v1/facts/screen?metric={metric}&year={year}", headers=auth).json()
        row = next(r for r in rows["data"] if r["cik"] == APPLE)
        assert row["display_name"] == want and row["predecessor"] is False, metric
    hit = client.get("/v1/companies/search?q=apple", headers=auth).json()["data"][0]
    assert hit["cik"] == APPLE and hit["display_name"] == want
    assert client.get(f"/v1/companies/{APPLE}", headers=auth).json()["display_name"] == want


def test_a_predecessor_figure_is_listed_under_its_successor(client, auth, db, ingested_aapl):
    year = _year(client, auth)
    _successor(db)
    for metric in ("revenue", "operating_margin"):
        rows = client.get(f"/v1/facts/screen?metric={metric}&year={year}", headers=auth).json()
        ciks = [r["cik"] for r in rows["data"]]
        assert APPLE not in ciks, metric  # listed once, under the current registrant
        row = next(r for r in rows["data"] if r["cik"] == HOLDCO)
        assert row["registrant_cik"] == APPLE and row["predecessor"] is True, metric
        assert row["display_name"] == "Apple Holdings Example Inc." and row["ticker"] == "AAPH"
        assert "predecessor registrant" in row["registrant_label"]
        assert row["source_url"].startswith("https://www.sec.gov/Archives/")
    # before the succession took effect, the figure is Apple's own
    early = client.get(f"/v1/facts/screen?metric=revenue&year={year}&as_of=2026-06-30",
                       headers=auth).json()  # fmt: skip
    row = next(r for r in early["data"] if r["cik"] == APPLE)
    assert row["predecessor"] is False and row["registrant_cik"] is None
