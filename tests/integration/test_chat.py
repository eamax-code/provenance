"""Company-intelligence chat: deterministic cited brief, phrased by a (fake or local) model."""

from __future__ import annotations

import os

import pytest

from app.api.routes_chat import check_answer
from app.services.llm import LLMReply, LLMUnavailable


class FakeLLM:
    def __init__(self, text="Revenue was $391.0 billion [2], up 2.0% [2]."):
        self.text = text
        self.calls = []

    def chat(self, messages, **kw):
        self.calls.append(messages)
        return LLMReply(text=self.text, model="fake:1b", duration_ms=1, output_tokens=10)


class DownLLM:
    def chat(self, messages, **kw):
        raise LLMUnavailable("The local language model could not be reached.")


@pytest.fixture
def items_aapl(db, sec_client, fake_sec, submissions_aapl):
    """AAPL with 8-K item codes, including an officer change (item 5.02)."""
    recent = {k: list(v) for k, v in submissions_aapl["filings"]["recent"].items()}
    recent["items"] = ["" for _ in recent["accessionNumber"]]
    for i, form in enumerate(recent["form"]):
        if form == "8-K":
            recent["items"][i] = "5.02,9.01"
            break
    fake_sec.add(
        "https://data.sec.gov/submissions/CIK0000320193.json",
        {**submissions_aapl, "filings": {"recent": recent}},
    )
    from app.services.ingestion import ingest_company

    return ingest_company(db, sec_client, "320193")


def test_filings_expose_8k_items(client, auth, items_aapl):
    data = client.get("/v1/companies/320193/filings?form_type=8-K", headers=auth).json()["data"]
    assert ["5.02", "9.01"] in [f["items"] for f in data]


def test_chat_resolves_company_and_grounds_answer(app, client, auth, items_aapl):
    fake = FakeLLM()
    app.state.llm_factory = lambda: fake
    r = client.post("/v1/chat", json={"message": "How is Apple's revenue growing?"}, headers=auth)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["company"]["cik"] == "0000320193" and body["model"] == "fake:1b"
    rev = next(m for m in body["brief"]["metrics"] if m["metric"] == "revenue")
    assert rev["display"] == "$391.0 billion" and rev["growth_pct"] == 2.0
    assert rev["source_url"].startswith("https://www.sec.gov/")
    assert body["checks"]["grounded"] is True
    lead = body["brief"]["leadership_filings"]
    assert lead and lead[0]["items"][0]["code"] == "5.02"
    context = fake.calls[0][1]["content"]
    assert "item 5.02" in context and "$391.0 billion" in context
    assert all(c["url"].startswith("https://") for c in body["citations"])


def test_chat_flags_numbers_not_in_context(app, client, auth, items_aapl):
    app.state.llm_factory = lambda: FakeLLM("Revenue will reach $500 billion [2] [99].")
    body = client.post("/v1/chat", json={"message": "AAPL outlook"}, headers=auth).json()
    assert body["checks"]["grounded"] is False
    assert body["checks"]["unknown_citations"] == [99]
    assert "500" in body["checks"]["unverified_numbers"]


def test_chat_without_model_returns_brief(app, client, auth, items_aapl):
    app.state.llm_factory = lambda: DownLLM()
    body = client.post("/v1/chat", json={"message": "x", "cik": "320193"}, headers=auth).json()
    assert body["answer"] is None and body["brief"]["metrics"]
    assert any("could not be reached" in n for n in body["notes"])


def test_chat_unknown_company_suggests(client, auth, items_aapl):
    body = client.post("/v1/chat", json={"message": "tell me about zzqx"}, headers=auth).json()
    assert body["company"] is None and body["answer"] is None


def test_chat_as_of_uses_point_in_time_brief(app, client, auth, items_aapl):
    app.state.llm_factory = lambda: FakeLLM("ok [1]")
    body = client.post(
        "/v1/chat", json={"message": "Apple", "as_of": "2024-01-15"}, headers=auth
    ).json()
    rev = next(m for m in body["brief"]["metrics"] if m["metric"] == "revenue")
    assert rev["period_end"] == "2023-09-30"


def test_check_answer_ignores_years_and_citations():
    ctx = "[1] Revenue: $391.0 billion; change +2.0%."
    assert check_answer("In 2024 revenue was $391.0 billion [1], +2.0% [1].", ctx, 1)["grounded"]


@pytest.mark.skipif(not os.environ.get("LLM_LIVE_TESTS"), reason="set LLM_LIVE_TESTS=1")
def test_live_local_model(app, client, auth, items_aapl, settings):
    settings.llm_enabled = True
    app.state.llm_factory = None
    body = client.post("/v1/chat", json={"message": "Summarise Apple"}, headers=auth).json()
    assert body["answer"] and body["checks"]["citations_used"], body


def test_strip_reasoning():
    from app.services.llm import strip_reasoning

    assert strip_reasoning("<think>plan</think>\nAnswer [1].") == "Answer [1]."
    assert strip_reasoning("Okay, let me think...\n</think>\n\nAnswer [2].") == "Answer [2]."
    assert strip_reasoning("Plain answer.") == "Plain answer."


def test_check_answer_accepts_form_names_from_prompt():
    answer = "Not shown here; see an 8-K item 5.02 or a DEF 14A [1]."
    assert check_answer(answer, "[1] Company: Apple Inc.", 1)["grounded"]


def test_chat_page_is_served_and_linked(client):
    r = client.get("/chat/")
    assert r.status_code == 200 and 'src="/chat.js"' in r.text
    assert client.get("/chat.js").status_code == 200 and client.get("/chat.css").status_code == 200
    assert 'href="/chat/"' in client.get("/").text
