import httpx
import pytest

from app.services.markets.http import MarketFetchError, MarketHttp


def _client(settings, tmp_path, handler, **kw):
    return MarketHttp(
        settings,
        http=httpx.Client(transport=httpx.MockTransport(handler)),
        cache_dir=tmp_path / "mc",
        sleep=lambda s: None,
        **kw,
    )


def test_download_caches_by_url(settings, tmp_path):
    calls = []

    def handler(request):
        calls.append(str(request.url))
        return httpx.Response(200, content=b"x" * 1000, headers={"Content-Type": "application/zip"})

    c = _client(settings, tmp_path, handler)
    f1 = c.download("https://example.test/file.zip")
    f2 = c.download("https://example.test/file.zip")
    assert f1.from_cache is False and f2.from_cache is True and f2.path.read_bytes() == b"x" * 1000
    assert len(calls) == 1 and f1.content_type == "application/zip"


def test_download_size_cap_and_errors(settings, tmp_path):
    c = _client(
        settings, tmp_path, lambda r: httpx.Response(200, content=b"y" * 2000), max_bytes=1000
    )
    with pytest.raises(MarketFetchError):
        c.download("https://example.test/big.zip")
    assert not list((tmp_path / "mc").glob("*.part"))
    c2 = _client(settings, tmp_path, lambda r: httpx.Response(503))
    with pytest.raises(MarketFetchError):
        c2.download("https://example.test/down.zip")
    with pytest.raises(MarketFetchError):
        c2.get_json("https://example.test/x.json")


def test_get_json_and_user_agent(settings, tmp_path):
    seen = {}

    def handler(request):
        seen["ua"] = request.headers["User-Agent"]
        return httpx.Response(200, json={"ok": True})

    c = _client(settings, tmp_path, handler)
    assert c.get_json("https://example.test/x.json") == {"ok": True}
    assert "contact=" in seen["ua"]
