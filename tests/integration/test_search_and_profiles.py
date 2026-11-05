"""GET /v1/search, GET /v1/companies/{cik}/profile and the stored profiles (issue #3, step 3)."""

from __future__ import annotations

from datetime import date

from sqlalchemy import select

from app.db.models import CompanyDocument, FilingSection
from app.services import documents, marts
from tests.integration.test_section_search import ACCESSION, CIK, INDEX, stored_s1  # noqa: F401

DEMO = {"X-API-Key": "demo"}


def _msft(db, sec_client):
    from app.services.ingestion import ingest_company

    ingest_company(db, sec_client, "789019")


def test_profile_cites_every_figure_and_filing(db, sec_client):
    _msft(db, sec_client)
    p = documents.build_profile(db, "0000789019", today=date(2024, 12, 31))
    assert p.markdown.startswith("# ") and "## Latest annual figures" in p.markdown
    assert "| Operating income |" in p.markdown and "## Recent filings" in p.markdown
    assert "total assets were $512.2 billion" in p.summary
    assert p.summary.count("[") == p.summary.count("]") >= 2
    numbers = {int(n) for n in documents._CITE.findall(p.summary)}
    assert numbers == {c["n"] for c in p.citations}
    assert all(c["url"].startswith("https://www.sec.gov/") for c in p.citations)
    # Only filing and document links: no data.sec.gov or other programmatic sources.
    assert "data.sec.gov" not in p.markdown and "first_detected" not in p.markdown
    assert documents.build_profile(db, "0000000001") is None


def test_summary_moves_citations_onto_another_list(db, sec_client):
    _msft(db, sec_client)
    p = documents.build_profile(db, "0000789019")
    taken = {}

    def cite(label, url):
        return taken.setdefault((label, url), 100 + len(taken))

    moved = documents.summary_for(p, cite)
    assert "[1]" not in moved and "[100]" in moved
    assert len(documents._CITE.findall(moved)) == len(documents._CITE.findall(p.summary))


def test_article_follows_how_the_form_is_said():
    assert documents.article("10-K") == "a 10-K"
    assert documents.article("8-K") == "an 8-K"
    assert documents.article("S-1/A") == "an S-1/A"
    assert documents.article("424B4") == "a 424B4"
    assert (
        documents.article("REVOKED") == "a REVOKED" and documents.article("SC 13G") == "an SC 13G"
    )


def test_risk_headings_are_the_section_categories():
    body = (
        "Risk Factors\nInvesting involves a high degree of risk.\n"
        "Risks Related to Our Business and Industry\nWe may lose money. Other\n"
        "risks related to autonomy and models. These risks could\n"
        "RISKS RELATED TO THIS OFFERING\nThe price may fall.\n"
        "Risks Related to Our Business and Industry\n"
    )
    assert documents.risk_headings(body) == [
        "Risks Related to Our Business and Industry",
        "Risks related to this offering",
    ]


def test_profile_lists_the_prospectus_risk_categories(db, stored_s1):  # noqa: F811
    section = db.scalars(select(FilingSection).where(FilingSection.item == "pr:risk")).one()
    section.text = "Risks Related to Our Compute Supply\n" + section.text
    db.commit()
    p = documents.build_profile(db, CIK)
    assert "## Risk factors" in p.markdown and "- Risks Related to Our Compute Supply" in p.markdown
    assert INDEX in p.markdown


def test_store_profiles_replaces_rows(db, sec_client):
    _msft(db, sec_client)
    marts.build_company_marts(db, ["0000789019"])
    assert documents.store_profiles(db, ["0000789019"]) == 1
    assert documents.store_profiles(db, ["0000789019"]) == 1
    rows = db.scalars(select(CompanyDocument)).all()
    assert len(rows) == 1 and rows[0].kind == "profile" and "| Total assets |" in rows[0].markdown


def test_profile_endpoint(client, db, sec_client, auth):
    _msft(db, sec_client)
    r = client.get("/v1/companies/789019/profile", headers=auth)
    assert r.status_code == 200
    body = r.json()
    assert body["cik"] == "0000789019" and body["markdown"].startswith("# ")
    assert body["summary"] and body["citations"]
    assert client.get("/v1/companies/123/profile", headers=auth).status_code == 404
    assert client.get("/v1/companies/abc/profile", headers=auth).status_code == 422


def test_search_endpoint_finds_companies_and_passages(client, db, stored_s1, auth):  # noqa: F811
    r = client.get("/v1/search", params={"q": "computing capacity"}, headers=auth)
    assert r.status_code == 200
    body = r.json()
    assert body["mode"] == "keyword"
    hit = body["sections"][0]
    assert (hit["cik"], hit["accession_number"], hit["source_url"]) == (CIK, ACCESSION, INDEX)
    assert hit["company"] == "Lumen Example Labs, Inc." and hit["snippet"]
    names = client.get("/v1/search", params={"q": "Lumen Example"}, headers=auth).json()
    assert names["companies"][0]["cik"] == CIK
    assert names["companies"][0]["filings_url"].startswith("https://www.sec.gov/cgi-bin/")
    assert "source_url" not in names["companies"][0]


def test_search_filters(client, db, stored_s1, auth):  # noqa: F811
    def sections(**params):
        r = client.get("/v1/search", params={"q": "computing capacity", **params}, headers=auth)
        assert r.status_code == 200
        return r.json()["sections"]

    assert sections(cik="2999001")
    assert sections(cik="320193") == []
    assert sections(form="S-1") and sections(form="10-K") == []
    assert sections(as_of="2026-10-19") == [] and sections(as_of="2026-10-20")
    bad = client.get("/v1/search", params={"q": "x y", "mode": "fuzzy"}, headers=auth)
    assert bad.status_code == 422


def test_demo_key_keyword_only_and_showcase_only(client, db, stored_s1, settings, monkeypatch):  # noqa: F811
    semantic = client.get("/v1/search", params={"q": "capacity", "mode": "semantic"}, headers=DEMO)
    assert semantic.status_code == 403
    assert semantic.json()["error"]["code"] == "semantic_needs_key"
    monkeypatch.setattr(settings, "public_showcase_ciks", "789019")
    r = client.get("/v1/search", params={"q": "computing capacity"}, headers=DEMO)
    assert r.status_code == 200 and r.json()["sections"] == []
    outside = client.get("/v1/search", params={"q": "computing capacity", "cik": CIK}, headers=DEMO)
    assert outside.status_code == 403
