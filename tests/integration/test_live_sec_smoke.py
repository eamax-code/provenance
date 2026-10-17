"""Optional live SEC smoke test. Runs only with SEC_LIVE_TESTS=1 and a real SEC_USER_AGENT."""

import os

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("SEC_LIVE_TESTS") != "1", reason="SEC_LIVE_TESTS != 1"
)


def test_live_submissions_and_facts(tmp_path):
    from app.core.config import Settings
    from app.services.fact_normalizer import normalize_company_facts
    from app.services.ingestion import parse_submissions
    from app.services.sec_client import SecClient

    settings = Settings(sec_cache_dir=str(tmp_path))
    assert "example.com" not in settings.sec_user_agent, "configure a real contact address"
    client = SecClient(settings)
    try:
        sub = client.fetch_submissions("320193")
        assert (
            sub.status_code == 200
            and sub.url == "https://data.sec.gov/submissions/CIK0000320193.json"
        )
        company, filings = parse_submissions(sub.data)
        assert company.cik == "0000320193" and filings
        facts = client.fetch_company_facts("320193")
        normalized = normalize_company_facts(facts.data, "0000320193")
        assert any(f.metric == "revenue" for f in normalized)
    finally:
        client.close()
