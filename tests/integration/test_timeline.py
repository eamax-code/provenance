"""X-05: GET /v1/companies/{cik}/timeline (docs/api-contracts-explorer.md)."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta

from app.db.models import DatedEvent, Filing, InsiderActivity, OfficerChange
from app.services import dated_events
from tests.integration.test_ownership_13f import loaded_13f  # noqa: F401 (fixture)

CIK = "0000320193"
URL = "https://www.sec.gov/Archives/edgar/data/320193/{}/{}-index.html"


def _filing(db, acc, form, filed, items=None):
    f = Filing(cik=CIK, accession_number=acc, form_type=form, filing_date=filed, items=items,
               source_url=URL.format(acc.replace("-", ""), acc),
               first_detected_at=datetime.now(UTC), quality_status="ok")  # fmt: skip
    db.add(f)
    return f


def _seed(db):
    today = date.today()
    _filing(db, "0001354457-26-001062", "25-NSE", today - timedelta(days=14))
    o = _filing(db, "0000320193-26-000090", "8-K", today - timedelta(days=30), "2.02,5.02,9.01")
    db.add(OfficerChange(
        cik=CIK, accession_number=o.accession_number, filing_date=o.filing_date, seq=0,
        person="Jane Example", role="Chief Financial Officer", change_type="appointment",
        verified=True, source_url=o.source_url, extractor_version="test",
    ))  # fmt: skip
    db.add(InsiderActivity(
        cik=CIK, activity_type="sec.insider_first_buy", activity_date=today - timedelta(days=9),
        filing_date=today - timedelta(days=8), accession_number="0001111111-26-000001",
        owners=json.dumps([{"owner_cik": "1111111", "name": "J. Example", "role": "Director"}]),
        detail=json.dumps({"shares": 1000, "value_usd": 200000}),
        source_url=URL.format("000111111126000001", "0001111111-26-000001"),
    ))  # fmt: skip
    p = _filing(db, "0000320193-26-000050", "424B4", today - timedelta(days=60))
    db.add(DatedEvent(
        cik=CIK, event_type=dated_events.LOCKUP_EXPIRY, event_date=today + timedelta(days=120),
        accession_number=p.accession_number, detail=json.dumps({"lockup_days": 180}),
        source_url=p.source_url,
    ))  # fmt: skip
    db.commit()
    return today


def test_timeline_mixes_every_source_newest_first(client, auth, db, items_aapl):
    _seed(db)
    body = client.get(f"/v1/companies/{CIK}/timeline?limit=200", headers=auth).json()
    types = {i["type"] for i in body["data"]}
    assert {"filing", "8k_item", "officer_change", "insider", "ipo"} <= types
    dates = [(i["date"], i["id"]) for i in body["data"]]
    assert dates == sorted(dates, reverse=True)
    assert body["notes"] == ["Information, not signals. Not investment advice."]
    officer = next(i for i in body["data"] if i["type"] == "officer_change")
    assert officer["details"]["person"] == "Jane Example" and officer["form_type"] == "8-K"
    lockup = next(i for i in body["data"] if i["details"].get("stage") == "lockup_expiry")
    assert lockup["upcoming"] and lockup["details"]["derived"]
    for i in body["data"]:  # every item links a filing; a 13F quarter would point to /ownership
        assert i["type"] == "13f_quarter" or i["filing_url"].startswith(
            "https://www.sec.gov/Archives/"
        )
    text = json.dumps(body)
    assert "first_detected" not in text and "data.sec.gov" not in text and "cusip" not in text


def test_form_25_never_says_the_company_was_delisted(client, auth, db, items_aapl):
    _seed(db)
    data = client.get(f"/v1/companies/{CIK}/timeline?types=filing", headers=auth).json()["data"]
    f25 = next(i for i in data if i["form_type"] == "25-NSE")
    assert f25["title"] == "Form 25: a security removed from listing"
    assert f25["event_type"] == "sec.delisting"
    from app.services.filing_events import SHORT_LABELS

    assert "delisted" not in SHORT_LABELS["sec.delisting"].lower()


def test_as_of_has_no_look_ahead_and_types_filter(client, auth, db, items_aapl):
    today = _seed(db)
    cut = (today - timedelta(days=20)).isoformat()
    data = client.get(f"/v1/companies/{CIK}/timeline?as_of={cut}&limit=200",
                      headers=auth).json()["data"]  # fmt: skip
    assert all(i["date"] <= cut or i["upcoming"] for i in data)
    assert not any(i["type"] == "insider" for i in data)  # filed after the cut
    assert not any(i.get("form_type") == "25-NSE" for i in data)
    only = client.get(f"/v1/companies/{CIK}/timeline?types=officer_change",
                      headers=auth).json()["data"]  # fmt: skip
    assert only and {i["type"] for i in only} == {"officer_change"}


def test_paging_and_bad_parameters(client, auth, db, items_aapl):
    _seed(db)
    first = client.get(f"/v1/companies/{CIK}/timeline?limit=2", headers=auth).json()
    assert first["meta"]["has_more"] and len(first["data"]) == 2
    nxt = client.get(f"/v1/companies/{CIK}/timeline?limit=2&cursor={first['meta']['next_cursor']}",
                     headers=auth).json()  # fmt: skip
    assert {i["id"] for i in nxt["data"]}.isdisjoint({i["id"] for i in first["data"]})
    bad = client.get(f"/v1/companies/{CIK}/timeline?types=filing,rumours", headers=auth)
    assert bad.status_code == 422 and bad.json()["error"]["code"] == "invalid_parameter"
    assert client.get(f"/v1/companies/{CIK}/timeline?cursor=zzz", headers=auth).status_code == 422
    assert client.get("/v1/companies/9999999/timeline", headers=auth).status_code == 404


def test_13f_quarters_point_to_ownership(client, auth, loaded_13f):  # noqa: F811
    data = client.get(f"/v1/companies/{CIK}/timeline?types=13f_quarter&as_of=2026-11-01",
                      headers=auth).json()["data"]  # fmt: skip
    assert data and all(i["type"] == "13f_quarter" and i["filing_url"] is None for i in data)
    q = data[0]["details"]
    assert q["quarter"] == "2026-06-30" and q["holders_count"] >= 1 and "flows" in q
    assert data[0]["date"] == "2026-08-14"  # the quarter's 45-day filing deadline


def test_insider_names_are_cased_in_filed_order(client, auth, db, items_aapl):
    today = date.today()
    db.add(InsiderActivity(
        cik=CIK, activity_type="sec.insider_large_sale", activity_date=today - timedelta(days=3),
        filing_date=today - timedelta(days=2), accession_number="0001222222-26-000001",
        owners=json.dumps([{"owner_cik": "1222222", "name": "LEVINSON ARTHUR D",
                            "role": "Director"}]),
        detail=json.dumps({"shares": 10000, "value_usd": 2500000}),
        source_url=URL.format("000122222226000001", "0001222222-26-000001"),
    ))  # fmt: skip
    db.commit()
    body = client.get(f"/v1/companies/{CIK}/timeline?types=insider", headers=auth).json()
    item = next(i for i in body["data"] if i["accession_number"] == "0001222222-26-000001")
    assert item["title"].startswith("Levinson Arthur D (Director) sold $2.5 million")
    wl = client.post("/v1/watchlists", json={"name": "x", "ciks": [CIK], "columns": ["last_event"]},
                     headers=auth).json()  # fmt: skip
    row = client.get(f"/v1/watchlists/{wl['id']}/rows", headers=auth).json()["data"][0]
    assert row["cells"]["last_event"]["title"].startswith("Levinson Arthur D (Director) sold")


def test_a_page_reads_only_the_filings_it_needs_and_matches_the_full_list(db, items_aapl):
    from sqlalchemy import select

    from app.db.models import Company
    from app.services import timeline

    _seed(db)
    for i in range(30):  # same-day filings straddle the page boundary
        _filing(db, f"0000320193-26-{900 + i:06d}", "424B2", date.today() - timedelta(days=i // 3))
    db.commit()
    c = db.scalar(select(Company).where(Company.cik == CIK))
    full = timeline.build(db, c)
    for offset, limit in ((0, 1), (0, 5), (5, 7), (10, 50), (0, 500)):
        part = timeline.build(db, c, need=offset + limit + 1)
        assert part[offset : offset + limit] == full[offset : offset + limit], (offset, limit)
        assert (len(part) > offset + limit) == (len(full) > offset + limit)
    assert len(timeline.build(db, c, need=3)) < len(full)  # it really reads fewer
    kinds = ("8k_item", "officer_change", "auditor_change", "ipo", "insider")
    assert timeline.build(db, c, kinds) == [i for i in full if i["type"] in kinds]
