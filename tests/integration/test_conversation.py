"""The chat's conversation flow (issue #7) and the quick-answer marts (issue #8)."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import select

from app.db.models import Company, Filing, MartCompany, MartFilingActivity
from app.services import marts
from app.services.humanize import clean
from app.services.llm import LLMReply

TODAY = date.today()


class FakeLLM:
    def __init__(self, text="Revenue was $391.0 billion [2], up 2.0% [2]."):
        self.text = text
        self.calls = []

    def chat(self, messages, **kw):
        self.calls.append(messages)
        return LLMReply(text=self.text, model="fake:1b", duration_ms=1, output_tokens=10)


def _filing(cik, n, form, filed):
    return Filing(
        cik=cik,
        accession_number=f"{cik}-26-{n:06d}",
        form_type=form,
        filing_date=filed,
        source_url=f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{cik}26{n:06d}/"
        f"{cik}-26-{n:06d}-index.html",
        first_detected_at=datetime.now(UTC),
        quality_status="ok",
    )


@pytest.fixture
def new_listings(db, ingested_aapl):
    """Two companies that went public recently (one a SPAC) and one that only registered."""
    now = datetime.now(UTC)
    rows = [
        ("0009000001", "Aspen Example Neuro, Inc.", "ASPX", "2834", 20),
        ("0009000002", "Example Acquisition Corp II", "EXAQ", "6770", 40),
        ("0009000003", "Still Registering Co", None, "7372", None),
    ]
    for cik, name, ticker, sic, ipo_days in rows:
        db.add(
            Company(
                cik=cik,
                legal_name=name,
                ticker=ticker,
                sic_code=sic,
                source_url="https://www.sec.gov/",
                first_detected_at=now,
                last_processed_at=now,
            )
        )
        db.add(_filing(cik, 1, "S-1", TODAY - timedelta(days=70)))
        if ipo_days:
            db.add(_filing(cik, 2, "424B4", TODAY - timedelta(days=ipo_days)))
    db.commit()
    marts.build_company_marts(db)
    marts.build_filing_activity(db)


def _chat(client, auth, message, **extra):
    r = client.post("/v1/chat", json={"message": message, **extra}, headers=auth)
    assert r.status_code == 200, r.text
    return r.json()


def test_company_mart_keeps_figures_with_their_filings(db, ingested_aapl):
    assert marts.build_company_marts(db) == 1
    row = db.get(MartCompany, "0000320193")
    assert row.latest_revenue == 391035000000 and row.latest_revenue_period_end == date(2024, 9, 28)
    history = json.loads(row.revenue_history)
    assert history[0]["accession"] and history[0]["url"].startswith("https://www.sec.gov/")
    assert [h["period_end"] for h in history] == sorted(
        (h["period_end"] for h in history), reverse=True
    )
    assert row.first_filing_date and row.latest_filing_date >= row.first_filing_date
    assert json.loads(row.latest_annual)["net_income"]["value"] > 0
    # One company can be rebuilt on its own.
    assert marts.build_company_marts(db, ["0000320193"]) == 1
    assert marts.build_filing_activity(db) > 0
    assert db.scalar(select(MartFilingActivity).where(MartFilingActivity.form_type == "10-K"))


def test_new_listings_are_answered_from_the_data(client, auth, new_listings, app):
    app.state.llm_factory = lambda: pytest.fail("a data question must not call the model")
    body = _chat(client, auth, "How mant new listings in the last 6 months", cik="320193")
    assert body["intent"] == "ipos" and body["answered_by"] == "data" and body["company"] is None
    assert body["answer"].startswith("2 companies went public in the last 6 months")
    assert "1 of them are blank-check companies (SPACs)" in body["answer"]
    table = body["widgets"][0]
    assert table["type"] == "table" and [r[0]["text"] for r in table["rows"]] == [
        "Aspen Example Neuro, Inc.",
        "Example Acquisition Corp II",
    ]
    assert table["rows"][0][2]["url"].startswith("https://www.sec.gov/")
    assert body["context"]["ciks"] == ["0009000001", "0009000002"]


def test_a_follow_up_uses_the_previous_answers_list(client, auth, new_listings):
    first = _chat(client, auth, "new listings in the last 6 months")
    body = _chat(
        client,
        auth,
        "What are these companies? show me their revenue for the last 3 years in a table",
        context=first["context"],
    )
    assert body["intent"] == "list_followup" and body["answered_by"] == "data"
    table = body["widgets"][0]
    assert table["columns"] == [
        "Company",
        "Ticker",
        "Latest year",
        "1 year earlier",
        "2 years earlier",
    ]
    assert len(table["rows"]) == 2 and all(r[2]["text"] == "—" for r in table["rows"])
    assert "2 of them have no annual report with revenue yet" in body["answer"]
    # Without the context the same words do not invent a list.
    alone = _chat(client, auth, "show me their revenue for the last 3 years")
    assert alone["intent"] != "list_followup"


def test_rankings_filers_counts_and_scope(client, auth, new_listings):
    top = _chat(client, auth, "top 5 companies by revenue")
    assert top["intent"] == "rank" and top["widgets"][0]["rows"][0][0]["text"] == "Apple Inc."
    filers = _chat(client, auth, "Who filed a 424B4 in the last 2 months?")
    assert filers["intent"] == "filers" and filers["answer"].startswith("2 companies filed a 424B4")
    count = _chat(client, auth, "how many S-1 filings in the last 3 months")
    assert count["intent"] == "filing_count" and count["answer"].startswith(
        "3 S-1 filings were filed"
    )
    week = _chat(client, auth, "who filed a 10-K this week")
    assert "this week" in week["answer"] and "in this week" not in week["answer"]
    price = _chat(client, auth, "What is Apple's stock price?")
    assert price["intent"] == "out_of_scope" and "share prices" in price["answer"]


def test_a_named_company_stays_in_the_company_flow(client, auth, new_listings, app):
    app.state.llm_factory = lambda: FakeLLM()
    body = _chat(client, auth, "How many filings did Apple make this year?")
    assert body["company"]["cik"] == "0000320193" and body["context"]["cik"] == "0000320193"


def test_the_model_sees_the_conversation_and_answers_plainly(client, auth, items_aapl, app):
    fake = FakeLLM(
        "Great question! Based on the provided CONTEXT, revenue was $391.0 billion [2]. "
        "Therefore, it grew 2.0% [2]. I hope this helps!"
    )
    app.state.llm_factory = lambda: fake
    body = _chat(
        client,
        auth,
        "and what about its revenue?",
        context={"intent": "question", "cik": "0000320193"},
        history=[{"q": "Summarise Apple", "a": "Apple reported revenue of $391.0 billion [2]."}],
    )
    assert body["company"]["cik"] == "0000320193"
    roles = [m["role"] for m in fake.calls[0]]
    assert roles == ["system", "user", "assistant", "user"]
    assert fake.calls[0][1]["content"] == "Summarise Apple"
    assert body["answer"] == "Revenue was $391.0 billion [2]. It grew 2.0% [2]."


def test_humanize_removes_residue_but_never_figures():
    assert clean("Sure! Revenue was $5.2 million [1]. Let me know if you need more.") == (
        "Revenue was $5.2 million [1]."
    )
    assert clean("The CONTEXT does not list them — only Apple.") == (
        "The filings do not list them, only Apple."
    )
    assert clean("U.S. revenue was $1.2 billion [1].") == "U.S. revenue was $1.2 billion [1]."
    assert clean("Overall, margins rose to 41.3% [2].") == "Margins rose to 41.3% [2]."
    assert clean("") == ""


def test_a_plain_figure_question_skips_the_model(client, auth, items_aapl, app):
    app.state.llm_factory = lambda: pytest.fail("a figure lookup must not call the model")
    body = _chat(client, auth, "What was Apple's revenue last year?")
    assert body["intent"] == "figure" and body["answered_by"] == "data"
    assert body["answer"].startswith(
        "Apple Inc.'s revenue was $391.0 billion in the fiscal year ended 2024-09-28 ["
    )
    assert "up 2.0% from $383.3 billion the year before" in body["answer"]
    assert body["checks"]["grounded"] is True


def test_a_why_question_still_goes_to_the_model(client, auth, items_aapl, app):
    fake = FakeLLM()
    app.state.llm_factory = lambda: fake
    body = _chat(client, auth, "Why is Apple's revenue so large?")
    assert body["answered_by"] == "model" and fake.calls


def test_model_answers_are_capped_at_whole_sentences(client, auth, items_aapl, app):
    long = " ".join(f"Point {i} is about revenue of $391.0 billion [2]." for i in range(9))
    fake = FakeLLM(long + " And the last one was cut off at the")
    app.state.llm_factory = lambda: fake
    body = _chat(client, auth, "Is Apple doing well?")
    assert body["answer"].count("[2]") == 3 and body["answer"].endswith("[2].")
    # Dated, so the model answers rather than the stored profile.
    overview = _chat(client, auth, "Tell me about Apple", as_of="2025-06-30")
    assert overview["answer"].count("[2]") == 5


def test_comparing_named_companies_builds_a_table(client, auth, db, sec_client, app):
    from app.services.ingestion import ingest_company

    ingest_company(db, sec_client, "320193")
    ingest_company(db, sec_client, "789019")
    marts.build_company_marts(db)
    app.state.llm_factory = lambda: pytest.fail("a comparison must not call the model")
    body = _chat(client, auth, "AAPL vs MSFT total assets")
    assert body["intent"] == "compare" and body["answered_by"] == "data"
    assert body["answer"].startswith("Latest annual total assets: Apple Inc. $")
    assert "Microsoft Corp $" in body["answer"] and "different months" in body["answer"]
    assert [r[0]["text"] for r in body["widgets"][0]["rows"]] == ["Apple Inc.", "Microsoft Corp"]
    assert body["context"]["ciks"] == ["0000320193", "0000789019"]
