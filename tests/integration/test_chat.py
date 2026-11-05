"""Company-intelligence chat: deterministic cited brief, phrased by a (fake or local) model."""

from __future__ import annotations

import os

import pytest

from app.api.routes_chat import add_missing_citations, check_answer
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


def test_filings_expose_8k_items(client, auth, items_aapl):
    data = client.get("/v1/companies/320193/filings?form_type=8-K", headers=auth).json()["data"]
    assert ["5.02", "9.01"] in [f["items"] for f in data]


def test_chat_resolves_company_and_grounds_answer(app, client, auth, items_aapl):
    fake = FakeLLM()
    app.state.llm_factory = lambda: fake
    r = client.post("/v1/chat", json={"message": "What drives Apple's revenue?"}, headers=auth)
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
    assert all(c["url"].startswith("https://www.sec.gov/") for c in body["citations"])
    assert "data.sec.gov" not in r.text and "source_url" not in body["company"]


def test_chat_flags_numbers_not_in_context(app, client, auth, items_aapl):
    app.state.llm_factory = lambda: FakeLLM("Revenue will reach $500 billion [2] [99].")
    body = client.post("/v1/chat", json={"message": "AAPL highlights"}, headers=auth).json()
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


def test_leadership_question_is_answered_from_data(app, client, auth, items_aapl):
    fake = FakeLLM()
    app.state.llm_factory = lambda: fake
    body = client.post(
        "/v1/chat",
        json={"message": "Any leadership changes at AAPL?", "as_of": "2024-12-31"},
        headers=auth,
    ).json()
    assert body["answered_by"] == "data" and body["model"] is None and not fake.calls
    lead = body["brief"]["leadership_filings"][0]
    assert f"[{lead['citation']}]" in body["answer"] and "item 5.02" in body["answer"]
    assert body["checks"]["grounded"] is True


def test_leadership_answer_admits_missing_item_codes(app, client, auth, ingested_aapl):
    app.state.llm_factory = lambda: FakeLLM()
    body = client.post(
        "/v1/chat", json={"message": "Did Apple's CFO resign?", "as_of": "2024-12-31"}, headers=auth
    ).json()
    assert body["answered_by"] == "data"
    assert "can't be ruled out" in body["answer"]
    cov = body["brief"]["coverage"]
    assert cov["eight_ks_since"] >= 1 and cov["eight_ks_with_items"] == 0


def test_leadership_answer_without_8ks_states_coverage(app, client, auth, items_aapl):
    body = client.post(
        "/v1/chat",
        json={"message": "Who is the CEO?", "cik": "320193", "as_of": "2023-12-31"},
        headers=auth,
    ).json()
    assert "No 8-K filings" in body["answer"] and "latest filed 2023-11-03" in body["answer"]
    assert not any("newer filings" in n for n in body["notes"])  # 58 days old: not stale


def test_pay_question_goes_to_model(app, client, auth, items_aapl):
    fake = FakeLLM()
    app.state.llm_factory = lambda: fake
    body = client.post(
        "/v1/chat", json={"message": "What is Apple's executive pay?"}, headers=auth
    ).json()
    assert body["answered_by"] == "model" and fake.calls


def test_check_answer_flags_citations_on_their_own_line():
    ctx = "[1] Company: Apple Inc.\n[2] Revenue: $391.0 billion."
    checks = check_answer("Not shown in the data.\n[1][2]", ctx, 2)
    assert checks["bare_citation_lines"] == ["[1][2]"] and checks["grounded"] is False


def test_brief_context_states_coverage(app, client, auth, items_aapl):
    fake = FakeLLM()
    app.state.llm_factory = lambda: fake
    client.post("/v1/chat", json={"message": "Why did AAPL margins change?"}, headers=auth)
    assert "Filings loaded in this service for the company: " in fake.calls[0][1]["content"]


def test_chat_page_is_served_and_linked(client):
    r = client.get("/chat/")
    assert r.status_code == 200 and 'src="/chat.js"' in r.text
    assert client.get("/chat.js").status_code == 200 and client.get("/chat.css").status_code == 200
    assert 'href="/chat/"' in client.get("/").text


def test_annual_figures_prefer_the_annual_report_over_a_proxy(db, items_aapl):
    from datetime import timedelta

    from sqlalchemy import select
    from sqlalchemy.orm import make_transient

    from app.db.models import Company, FinancialFact
    from app.services import intel

    company = db.scalar(select(Company).where(Company.cik == "0000320193"))
    before = next(m for m in intel.build_brief(db, company).metrics if m["metric"] == "revenue")
    fact = db.scalar(
        select(FinancialFact).where(
            FinancialFact.accession_number == before["accession_number"],
            FinancialFact.metric == "revenue",
            FinancialFact.period_class == "annual",
            FinancialFact.derived.is_(False),
            FinancialFact.value == before["value"],
        )
    )
    make_transient(fact)
    fact.id = None
    fact.observation_key = "proxy-copy"
    fact.form_type = "DEF 14A"
    fact.accession_number = "0000000000-99-000001"
    fact.filed_date = fact.filed_date + timedelta(days=60)
    db.add(fact)
    db.commit()
    after = next(m for m in intel.build_brief(db, company).metrics if m["metric"] == "revenue")
    assert after["accession_number"] == before["accession_number"]


def test_uncited_sentences_get_the_line_holding_their_numbers():
    lines = [
        "[1] Company: Costco.",
        "[2] Revenue, fiscal year ended 2026-08-30: $303.2 billion; prior year (ended "
        "2025-08-31) $275.2 billion; change +10.1%. Filed 2026-10-07 (10-K).",
    ]
    text = "Revenue grew +10.1% to $303.2 billion in the year ended 2026-08-30. Strong year."
    out, added = add_missing_citations(text, lines)
    assert added == 1
    assert out == (
        "Revenue grew +10.1% to $303.2 billion in the year ended 2026-08-30 [2]. Strong year."
    )
    filed, _ = add_missing_citations("It is from the 10-K filed 2026-10-07.", lines)
    assert filed.endswith("2026-10-07 [2].")
    vague, _ = add_missing_citations("See the 10-K.", lines)
    assert "[" not in vague  # a bare form number is not evidence
    same, none = add_missing_citations("Revenue was $999.0 billion.", lines)
    assert none == 0 and "[" not in same  # an unknown number is never given a citation


def test_leadership_answer_counts_all_filings_not_just_those_listed(
    app, client, auth, db, items_aapl
):
    from datetime import date, timedelta

    from sqlalchemy import select

    from app.db.models import Filing

    base = db.scalar(select(Filing).where(Filing.items.like("%5.02%")))
    for i in range(6):
        db.add(
            Filing(
                cik=base.cik,
                accession_number=f"0000320193-24-90000{i}",
                form_type="8-K",
                filing_date=date(2024, 6, 1) + timedelta(days=i),
                items="5.02",
                source_url=base.source_url,
                first_detected_at=base.first_detected_at,
                quality_status="ok",
            )
        )
    db.commit()
    body = client.post(
        "/v1/chat", json={"message": "Apple CEO change?", "as_of": "2024-12-31"}, headers=auth
    ).json()
    assert "7 8-Ks with item 5.02" in body["answer"] and "the latest 5" in body["answer"]


def test_name_match_prefers_the_listed_company(db, items_aapl):
    from sqlalchemy import select

    from app.db.models import Company
    from app.services import intel

    listed = db.scalar(select(Company).where(Company.cik == "0000320193"))
    db.add(
        Company(
            cik="0000999991",
            legal_name="Apple A Holdings",
            ticker=None,
            source_url="https://data.sec.gov/submissions/CIK0000999991.json",
            first_detected_at=listed.first_detected_at,
        )
    )
    db.commit()
    assert intel.resolve_company(db, "how is apple doing").cik == "0000320193"
    db.add(
        Company(
            cik="0000999992",
            legal_name="Apple Hospitality REIT, Inc.",
            ticker="APLE",
            source_url="https://data.sec.gov/submissions/CIK0000999992.json",
            first_detected_at=listed.first_detected_at,
        )
    )
    db.commit()
    assert intel.resolve_company(db, "leadership changes at Apple").cik == "0000320193"


def test_plan_reads_metric_and_years():
    from app.services.widgets import plan

    p = plan("How's apples growth in revenue for the last 5 years")
    assert (p.kind, p.metric, p.years) == ("trend", "revenue", 5)
    assert plan("net income over the past three years").metric == "net_income"
    assert plan("net income over the past three years").years == 3
    assert plan("What was Apple's operating profit?").kind == "metric"
    assert plan("How fast is Apple growing?").metric == "revenue"
    assert plan("Any changes to executive pay?").kind == "overview"  # "changes" alone is no trend


def test_growth_question_is_charted_from_cited_figures(app, client, auth, items_aapl):
    fake = FakeLLM()
    app.state.llm_factory = lambda: fake
    body = client.post(
        "/v1/chat",
        # A follow-up from another company's chat: the named company must win over the cik.
        json={"message": "How's apples growth in revenue for the last 5 years", "cik": "1"},
        headers=auth,
    ).json()
    assert body["company"]["cik"] == "0000320193"
    assert body["answered_by"] == "data" and body["intent"] == "trend" and not fake.calls
    chart = body["widgets"][0]
    assert chart["type"] == "chart" and chart["metric"] == "revenue"
    points = chart["points"]
    assert 2 <= len(points) <= 6
    assert [p["period_end"] for p in points] == sorted(p["period_end"] for p in points)
    by_n = {c["n"]: c for c in body["citations"]}
    for p in points:
        assert by_n[p["citation"]]["url"] == p["source_url"]
    assert points[-1]["display"] in body["answer"]
    assert body["checks"]["grounded"] is True, body["checks"]


def test_overview_question_gets_figure_tiles(app, client, auth, items_aapl):
    app.state.llm_factory = lambda: FakeLLM()
    body = client.post("/v1/chat", json={"message": "Summarise Apple"}, headers=auth).json()
    assert body["answered_by"] == "data" and body["intent"] == "summary"  # tiles still shown
    tiles = body["widgets"][0]
    assert tiles["type"] == "stats"
    rev = next(i for i in tiles["items"] if i["metric"] == "revenue")
    assert rev["value"] == "$391.0 billion" and rev["spark"]


def test_leadership_answers_carry_no_widgets(app, client, auth, items_aapl):
    body = client.post(
        "/v1/chat", json={"message": "Apple CEO change?", "as_of": "2024-12-31"}, headers=auth
    ).json()
    assert body["widgets"] == []


def test_counts_in_a_question_are_not_ciks(db, items_aapl):
    from app.services import intel

    assert intel.resolve_company(db, "revenue for the last 5 years") is None


def test_plural_words_do_not_shadow_a_named_company(db, items_aapl):
    from sqlalchemy import select

    from app.db.models import Company
    from app.services import intel

    listed = db.scalar(select(Company).where(Company.cik == "0000320193"))
    db.add(
        Company(
            cik="0000999993",
            legal_name="Change Agents Corp",
            ticker="CHGA",
            source_url="https://data.sec.gov/submissions/CIK0000999993.json",
            first_detected_at=listed.first_detected_at,
        )
    )
    db.commit()
    assert intel.resolve_company(db, "Recent leadership changes at Apple?").cik == "0000320193"
    assert intel.resolve_company(db, "how are apples sales").cik == "0000320193"


def test_a_whole_name_beats_a_word_that_starts_another_name(db, items_aapl):
    from sqlalchemy import select

    from app.db.models import Company
    from app.services import intel

    listed = db.scalar(select(Company).where(Company.cik == "0000320193"))
    db.add(
        Company(
            cik="0000999994",
            legal_name="Quickturn Holdings",
            ticker="QTH",
            source_url="https://data.sec.gov/submissions/CIK0000999994.json",
            first_detected_at=listed.first_detected_at,
        )
    )
    db.commit()
    assert intel.resolve_company(db, "How quick is Apple growing?").cik == "0000320193"


def test_display_name_reads_naturally():
    from app.services.intel import display_name

    assert display_name("COSTCO WHOLESALE CORP /NEW") == "Costco Wholesale Corp"
    assert display_name("Apple Inc.") == "Apple Inc."
    assert display_name("ABC HOLDINGS LLC") == "Abc Holdings LLC"


def test_a_common_word_that_is_a_ticker_loses_to_a_named_company(db, items_aapl):
    from sqlalchemy import select

    from app.db.models import Company
    from app.services import intel

    listed = db.scalar(select(Company).where(Company.cik == "0000320193"))
    db.add(
        Company(
            cik="0000999995",
            legal_name="Fastenal Co",
            ticker="FAST",
            source_url="https://data.sec.gov/submissions/CIK0000999995.json",
            first_detected_at=listed.first_detected_at,
        )
    )
    db.commit()
    assert intel.resolve_company(db, "How fast is Apple growing?").cik == "0000320193"
    assert intel.resolve_company(db, "FAST revenue").cik == "0000999995"


def test_follow_up_stays_on_the_company_unless_another_is_named(db, items_aapl):
    from sqlalchemy import select

    from app.db.models import Company
    from app.services import intel

    listed = db.scalar(select(Company).where(Company.cik == "0000320193"))
    for cik, name, ticker in [
        ("0000999996", "Youdao, Inc.", "DAO"),
        ("0000999997", "Canaan Inc.", "CAN"),
        ("0000999998", "Moregain Pictures, Inc.", None),
    ]:
        db.add(
            Company(
                cik=cik,
                legal_name=name,
                ticker=ticker,
                source_url=f"https://data.sec.gov/submissions/CIK{cik}.json",
                first_detected_at=listed.first_detected_at,
            )
        )
    db.commit()
    for q in [
        "What other information do you have?",
        "Any insights that can be shared",
        "Tell me more",
    ]:
        assert intel.resolve_company(db, q) is None, q
        assert intel.resolve_company(db, q, follow_up=True) is None, q
    assert intel.resolve_company(db, "what about youdao", follow_up=True).cik == "0000999996"
    assert intel.resolve_company(db, "And Canaan?", follow_up=True).cik == "0000999997"
    assert intel.resolve_company(db, "how is CAN doing", follow_up=True).cik == "0000999997"
    assert intel.resolve_company(db, "how are apples sales", follow_up=True).cik == "0000320193"


def test_follow_up_without_a_company_uses_the_current_one(app, client, auth, items_aapl):
    app.state.llm_factory = lambda: FakeLLM()
    body = client.post(
        "/v1/chat",
        json={"message": "What other information do you have?", "cik": "320193"},
        headers=auth,
    ).json()
    assert body["company"]["cik"] == "0000320193" and body["answer"]


def _add_companies(db, names):
    from sqlalchemy import select

    from app.db.models import Company

    first = db.scalar(select(Company)).first_detected_at
    for i, (name, ticker) in enumerate(names):
        db.add(
            Company(
                cik=f"00009998{i:02d}",
                legal_name=name,
                ticker=ticker,
                source_url="https://www.sec.gov/",
                first_detected_at=first,
            )
        )
    db.commit()


def test_coverage_question_is_answered_from_the_data(app, client, auth, items_aapl, db):
    # Issue #1: "active" used to pick ActiveCare, Inc. and answer with its 2016 figures.
    _add_companies(db, [("ACTIVECARE, INC.", None), ("Active Network Inc", None)])
    r = client.post(
        "/v1/chat",
        json={"message": "how many active publics do you have as of today?"},
        headers=auth,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["intent"] == "coverage" and body["company"] is None and body["widgets"] == []
    assert body["answered_by"] == "data"
    assert "1 US public company loaded" in body["answer"] and "last 12 months" in body["answer"]
    # A company that is clearly named still gets its own answer.
    named = client.post(
        "/v1/chat", json={"message": "How many filings does Apple have?"}, headers=auth
    ).json()
    assert named["company"]["cik"] == "0000320193" and named["intent"] != "coverage"


def test_a_common_word_never_picks_a_company_on_its_own(db, items_aapl):
    from app.services import intel

    _add_companies(db, [("ACTIVECARE, INC.", None), ("Active Network Inc", "ACTN")])
    assert intel.resolve_company(db, "how active is the market") is None
    assert intel.resolve_company(db, "Activecare revenue").legal_name == "ACTIVECARE, INC."
    assert intel.resolve_company(db, "ActiveCare Inc").legal_name == "ACTIVECARE, INC."
    assert intel.resolve_company(db, "summarise apple").cik == "0000320193"
    assert intel.resolve_company(db, "how is the company doing today") is None


def test_typos_resolve_to_the_nearest_name(db, items_aapl):
    from app.services import intel
    from app.services.company_lookup import search_companies, typo_distance

    _add_companies(
        db,
        [("AMAZON COM INC", "AMZN"), ("AMAZE HOLDINGS, INC.", "AMZE"), ("MICROSOFT CORP", "MSFT")],
    )
    assert intel.resolve_company(db, "Summarise Mircosoft").legal_name == "MICROSOFT CORP"
    assert intel.resolve_company(db, "how is amazn doing").legal_name == "AMAZON COM INC"
    assert intel.resolve_company(db, "Appel revenue").cik == "0000320193"
    hits, _ = search_companies(db, "mircosoft", limit=3)
    assert [(h.company.ticker, h.match_type) for h in hits] == [("MSFT", "name_fuzzy")]
    # Exact and prefix matches always outrank a typo; short words never get typo matching.
    assert search_companies(db, "micro", limit=3)[0][0].match_type == "name_prefix"
    assert search_companies(db, "aple", limit=3)[0] == []
    assert typo_distance("amazn", "amazon") < typo_distance("amazn", "amaze")
    assert typo_distance("mircosoft", "microsoft") < 1


def test_unclear_question_offers_the_nearest_companies(client, auth, items_aapl, db):
    _add_companies(db, [("ACTIVECARE, INC.", None)])
    body = client.post("/v1/chat", json={"message": "what is activ"}, headers=auth).json()
    assert body["company"] is None and body["answer"] is None
    assert any("ACTIVECARE" in s["legal_name"] for s in body["suggestions"])
    assert "Which company do you mean?" in body["notes"][0]


def test_summary_is_answered_from_the_profile(app, client, auth, ingested_aapl):
    fake = FakeLLM()
    app.state.llm_factory = lambda: fake
    body = client.post("/v1/chat", json={"message": "Summarise Apple"}, headers=auth).json()
    assert body["intent"] == "summary" and body["answered_by"] == "data" and not fake.calls
    assert body["checks"]["grounded"] is True and not body["checks"]["unknown_citations"]
    labels = [c["label"] for c in body["citations"]]
    assert len(labels) == len(set(labels))  # the brief's entries are reused, not repeated
    # A point-in-time question still goes to the model, which reads the brief as of that date.
    dated = client.post(
        "/v1/chat", json={"message": "Summarise Apple", "as_of": "2024-12-31"}, headers=auth
    ).json()
    assert dated["intent"] == "question"
