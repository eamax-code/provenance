"""GDELT as the commercial-safe headline source for forecasts (GH #14)."""

from __future__ import annotations

import httpx
import pytest

from app.services import news

ARTICLES = [
    {"url": "https://a.example/1", "title": "Nvidia revenue tops $57 . 0 billion , beats views",
     "seendate": "20261113T210000Z", "domain": "a.example"},
    {"url": "https://b.example/2", "title": "Budget deliberations to start",
     "seendate": "20261114T000000Z", "domain": "b.example"},  # no company name: dropped
    {"url": "http://c.example/3", "title": "Nvidia guidance raised", "seendate": "20261112T000000Z",
     "domain": "c.example"},  # not https: dropped
    {"url": "https://d.example/4", "title": "NVIDIA revenue tops $57 . 0 billion , beats views",
     "seendate": "20261113T220000Z", "domain": "d.example"},  # duplicate title: dropped
    "not an article",
]  # fmt: skip


def test_parse_keeps_relevant_https_headlines_and_fixes_spacing():
    out = news.parse_gdelt(ARTICLES, '"Nvidia" (earnings OR revenue)', 5)
    assert [h.url for h in out] == ["https://a.example/1"]
    h = out[0]
    assert h.title == "Nvidia revenue tops $57.0 billion, beats views"
    assert h.published == "2026-11-13" and h.source == "a.example"


def test_provider_sends_the_query_and_reads_json(settings, monkeypatch):
    seen = {}

    def handler(request):
        seen.update(dict(request.url.params))
        return httpx.Response(200, json={"articles": ARTICLES})

    g = news.GdeltDoc(settings, http=httpx.Client(transport=httpx.MockTransport(handler)))
    out = g.search('"Nvidia" (earnings OR revenue)', 3)
    assert len(out) == 1
    assert seen["query"].endswith("sourcelang:english") and seen["mode"] == "artlist"
    assert seen["format"] == "json" and seen["timespan"] == "30d"
    bad = news.GdeltDoc(settings, http=httpx.Client(transport=httpx.MockTransport(
        lambda r: httpx.Response(200, text="Please limit requests"))))  # fmt: skip
    with pytest.raises(news.NewsUnavailable):
        bad.search('"Nvidia"', 3)


def test_provider_choice_and_production_rule(settings, monkeypatch):
    assert isinstance(news.provider_for(settings), news.GoogleNewsRSS)
    monkeypatch.setattr(settings, "news_provider", "gdelt")
    assert isinstance(news.provider_for(settings), news.GdeltDoc)
    monkeypatch.setattr(settings, "app_env", "production")
    monkeypatch.setattr(settings, "news_enabled", True)
    assert not any("NEWS_PROVIDER" in p for p in settings.validate_for_runtime())
    monkeypatch.setattr(settings, "news_provider", "google_rss")
    assert any("NEWS_PROVIDER=google_rss" in p for p in settings.validate_for_runtime())
