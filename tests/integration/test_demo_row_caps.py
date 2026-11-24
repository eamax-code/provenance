"""2026-11-24 (provenance-ui, provenance-pm): the demo key gets at most 10 rows on any list
(docs/contracts/README.md). The 24 Nov endpoints carry their rows under their own keys
(`plans`, `proposed_sales`, `threads`, the tree's `{"total", "data"}`), which the demo cap did not
trim: insider-plans returned 13 proposed sales. Every endpoint and chat intent of the window is
checked here with more than 10 rows seeded."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from app.db.models import CommentLetter, FormDFiling, Subsidiary, TradingPlan
from tests.integration.test_insider_plans_pay import _notice

CIK = "0000320193"
DEMO = {"X-API-Key": "demo"}
N = 13


@pytest.fixture(autouse=True)
def _reset_limits():
    from app.api import dependencies

    dependencies.demo_minute_limiter.reset()
    dependencies.demo_day_limiter.reset()
    yield
    dependencies.demo_minute_limiter.reset()
    dependencies.demo_day_limiter.reset()


def _lists(x, path=""):
    """Every list in a response with its path, at any depth."""
    if isinstance(x, list):
        yield path, x
        for i, v in enumerate(x):
            yield from _lists(v, f"{path}[{i}]")
    elif isinstance(x, dict):
        for k, v in x.items():
            yield from _lists(v, f"{path}.{k}")


def _seed(db):
    d = date(2026, 11, 2)
    for i in range(N):
        _notice(db, f"0001959173-26-{i:06d}", f"Seller {i}", f"000{i:07d}", d + timedelta(days=i))
        db.add(TradingPlan(cik=CIK, accession_number=f"0000320193-26-{i:06d}", form_type="10-Q",
                           filing_date=date(2026, 1, 30), period=date(2025, 12, 27),
                           member=f"Individual=P{i}", person_name=f"Person {i}", title="Director",
                           action="adopted", plan_type="rule_10b5_1",
                           plan_date=date(2025, 11, 1) + timedelta(days=i), duration_days=400,
                           expiration_date=date(2026, 12, 31), source="test"))  # fmt: skip
        db.add(CommentLetter(accession_number=f"0000000000-25-{i:06d}", cik=CIK,
                             form_type="UPLOAD", filing_date=date(2025, 3, 1) + timedelta(days=i),
                             file_number=f"333-{i:06d}", subject=f"Form S-3 {i}", kind="letter",
                             readable=True, closes_review=False, topics="[]", text="x",
                             source_url=f"https://www.sec.gov/Archives/edgar/data/320193/{i}.pdf",
                             reader_version="test"))  # fmt: skip
        db.add(
            Subsidiary(
                id=500 + i,
                cik=CIK,
                accession_number="0000320193-25-000079",
                form_type="10-K",
                filing_date=date(2025, 10, 31),
                exhibit="EX-21.1",
                position=i,
                name=f"Apple Sub {i}",
                jurisdiction="Ireland",
                source_url="https://www.sec.gov/Archives/edgar/data/320193/x/ex21.htm",
            )
        )
        db.add(FormDFiling(accession_number=f"0000320193-26-9{i:05d}", file_number=f"021-{i}",
                           form_type="D", filing_date=date(2026, 9, 1) + timedelta(days=i),
                           cik=CIK, issuer_name="Apple Inc.", industry_group="Biotechnology",
                           total_offering_amount=60_000_000, total_amount_sold=55_000_000 + i,
                           exemptions="06b", related_persons="[]", is_latest=True,
                           quality_status="ok", source="test"))  # fmt: skip
    db.commit()


def test_demo_key_trims_every_list_of_the_24_nov_endpoints(client, db, ingested_aapl, settings):
    _seed(db)
    cap = settings.demo_max_limit
    paths = [
        f"/v1/companies/{CIK}/insider-plans?since=2025-01-01",
        f"/v1/companies/{CIK}/executive-pay",
        f"/v1/companies/{CIK}/comment-letters?since=2019-01-01",
        f"/v1/companies/{CIK}/corporate-tree",
        f"/v1/companies/{CIK}/calendar",
        f"/v1/calendar?ciks={int(CIK)}",
        f"/v1/companies/{CIK}/private-raises",
        "/v1/private-raises",
    ]
    seen = set()
    for p in paths:
        r = client.get(p, headers=DEMO)
        assert r.status_code == 200, (p, r.text[:200])
        for where, rows in _lists(r.json()):
            if where.endswith(".notes"):
                continue
            assert len(rows) <= cap, (p, where, len(rows))
            if len(rows) == cap:
                seen.add(where)
    # the seeded lists were really over the cap, and were trimmed rather than empty
    assert {".proposed_sales", ".plans", ".threads", ".subsidiaries.data", ".data"} <= seen
    tree = client.get(f"/v1/companies/{CIK}/corporate-tree", headers=DEMO).json()
    assert tree["subsidiaries"]["total"] == N  # the total still says how many there are
    full = client.get(f"/v1/companies/{CIK}/insider-plans?since=2025-01-01",
                      headers={"X-API-Key": "x"})  # fmt: skip
    assert full.status_code in (401, 403)  # sanity: an unknown key is refused, not uncapped


def test_demo_chat_tables_are_capped(client, db, ingested_aapl, settings):
    _seed(db)
    r = client.post("/v1/chat", json={"message": "Who raised money in biotech in 2026?"},
                    headers=DEMO).json()  # fmt: skip
    tables = [w for w in r["widgets"] if w["type"] == "table"]
    assert r["intent"] == "private_raises" and tables
    assert all(len(t["rows"]) <= settings.demo_max_limit for t in tables)


@pytest.mark.parametrize("n, note, total", [(20, None, 20), (50, "Showing 50 of 73.", 73)])
def test_demo_chat_screens_and_lists_are_capped(client, monkeypatch, settings, n, note, total):
    """2026-11-24 (provenance-pm): every chat table, screens and lists from before the window
    included, shows the demo key at most 10 rows, with a total that counts every row."""
    from app.services import conversation

    rows = [[{"text": f"Company {i}"}, {"text": "$1.0 billion"}] for i in range(n)]
    table = conversation._table("Screen: revenue over $1.0 billion", ["Company", "Revenue"], rows,
                                note=note)  # fmt: skip
    found = conversation.DataAnswer(f"{total} companies match.", "screen",
                                    [{"type": "screen", "parameters": {}, "matches": total},
                                     table])  # fmt: skip
    monkeypatch.setattr(conversation, "plan", lambda *a, **k: conversation.Plan("screen"))
    monkeypatch.setattr(conversation, "answer", lambda *a, **k: found)
    cap = settings.demo_max_limit
    r = client.post("/v1/chat", json={"message": "Companies with revenue over $1B"},
                    headers=DEMO).json()  # fmt: skip
    tables = [w for w in r["widgets"] + r["blocks"] if w.get("type") == "table"]
    assert tables and all(len(t["rows"]) == cap and t["total"] == total for t in tables)
    assert tables[0]["note"].startswith(f"Showing {cap} of {total}.")
    assert tables[0]["note"].endswith(f"The demo key shows at most {cap} rows.")
