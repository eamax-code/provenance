"""Developer pages, the API reference, the changelog, and the 404 and error pages, all in the
shared layout (GH #11, #20, #21)."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import sync_site_shell  # noqa: E402

SITE = sync_site_shell.SITE
HTML = {"Accept": "text/html,application/xhtml+xml"}


def test_developer_pages_are_in_the_shared_layout(client):
    for path, hook in {
        "/developers/": "/docs.js",
        "/docs/": "/docs/reference.js",
        "/changelog/": 'id="policy"',
    }.items():
        r = client.get(path)
        assert r.status_code == 200 and r.headers["content-type"].startswith("text/html"), path
        assert 'class="site-bar"' in r.text and 'class="site-foot"' in r.text, path
        assert hook in r.text and 'id="main"' in r.text, path
    # the old address still works, and lands on the reference in the site's layout
    r = client.get("/docs")
    assert r.status_code == 200 and "/docs/reference.js" in r.text and "swagger" not in r.text


def test_quickstart_covers_the_three_languages_and_the_guides(client):
    html = client.get("/developers/").text
    for needle in ("curl -s", "from provenance_client import Client", "await fetch(",
                   'id="as-of"', 'id="events"', 'id="webhooks"', 'id="listings"',
                   'id="errors"', 'id="limits"', "X-Signature", "/v1/public/plans"):  # fmt: skip
        assert needle in html or needle in client.get("/docs.js").text, needle
    # every error code the docs promise is one the API can return
    app_src = "\n".join(p.read_text() for p in Path("app").rglob("*.py"))
    for code in ("demo_scope", "invalid_cursor", "watch_limit_reached", "export_limit_exceeded",
                 "quota_exceeded", "stream_limit", "semantic_needs_key"):  # fmt: skip
        assert f"<code>{code}</code>" in html and f'"{code}"' in app_src, code


def test_reference_renders_the_live_openapi_without_injecting_html(client):
    js = client.get("/docs/reference.js").text
    assert 'fetch("/openapi.json")' in js
    assert "innerHTML" not in js  # descriptions are set as text, never parsed
    spec = client.get("/openapi.json").json()
    tags = {op.get("tags", ["other"])[0] for ops in spec["paths"].values() for op in ops.values()}
    for tag in tags:  # every group the API has gets a heading
        assert f'["{tag}",' in js, tag


def test_changelog_states_the_versioning_policy(client):
    html = client.get("/changelog/").text
    for needle in ("/v1", "Deprecation", "Sunset", "mapping_version", "12 months"):
        assert needle in html, needle
    assert html.count('<li><time datetime="') >= 5


def test_browsers_get_the_404_page_and_the_api_keeps_json(client):
    r = client.get("/no-such-page/", headers=HTML)
    assert r.status_code == 404 and r.headers["content-type"].startswith("text/html")
    assert "This page is not here" in r.text and 'class="site-bar"' in r.text
    assert 'name="robots" content="noindex"' in r.text
    for path, headers in (("/v1/no-such", HTML), ("/no-such-page/", {}), ("/v1/no-such", {})):
        r = client.get(path, headers=headers)
        assert r.status_code == 404 and r.json()["error"]["code"] == "not_found", (path, headers)
    r = client.get("/companies/abc", headers=HTML)  # not a CIK: never someone else's page
    assert r.status_code == 404 and "This page is not here" in r.text
    assert client.get("/companies/0000320193", headers=HTML).status_code == 200
    r = client.get("/v1/companies/0000000001", headers={**HTML, "X-API-Key": "demo"})
    assert r.headers["content-type"].startswith("application/json")


def test_unhandled_errors_show_the_error_page_to_browsers(settings):
    from fastapi.testclient import TestClient

    from app.main import create_app

    app = create_app(settings)

    def boom():
        raise RuntimeError("kaboom")

    app.add_api_route("/boom-page", boom)
    app.router.routes.insert(0, app.router.routes.pop())  # ahead of the static site

    with TestClient(app, raise_server_exceptions=False) as c:
        r = c.get("/boom-page", headers=HTML)
        assert r.status_code == 500 and "Something went wrong" in r.text
        assert "kaboom" not in r.text and r.headers["cache-control"] == "no-store"
        r = c.get("/boom-page")
        assert r.status_code == 500 and r.json()["error"]["code"] == "internal_error"


def test_every_page_has_a_main_landmark_and_a_skip_link():
    header = (SITE / "shell" / "header.html").read_text()
    assert header.startswith('<a class="skip-link" href="#main">')
    for page in sync_site_shell.PAGES:
        html = (SITE / page).read_text()
        assert html.count('id="main"') == 1, page
        assert html.count("<main") == 1 and html.count("</main>") == 1, page
        assert 'class="skip-link" href="#main"' in html, page
        assert '<html lang="en">' in html, page


def test_robots_and_sitemap(client, ingested_aapl, settings, monkeypatch):
    from app.services import public as public_service

    public_service.reset_cache()
    robots = client.get("/robots.txt")
    assert robots.status_code == 200 and "Disallow: /v1/" in robots.text
    assert "Disallow: /poc/" in robots.text
    assert "Sitemap: http://testserver/sitemap.xml" in robots.text
    r = client.get("/sitemap.xml")
    assert r.status_code == 200 and r.headers["content-type"].startswith("application/xml")
    for path in ("/", "/developers/", "/docs/", "/companies/", "/changelog/"):
        assert f"<loc>http://testserver{path}</loc>" in r.text, path
    assert "<loc>http://testserver/companies/0000320193</loc>" in r.text  # showcase companies
    assert "/poc/" not in r.text and "/v1/" not in r.text
    monkeypatch.setattr(settings, "public_base_url", "https://provenance.example/")
    public_service.reset_cache()
    assert "Sitemap: https://provenance.example/sitemap.xml" in client.get("/robots.txt").text
    assert "<loc>https://provenance.example/</loc>" in client.get("/sitemap.xml").text
    assert "robots.txt" not in str(client.get("/openapi.json").json()["paths"])


def test_every_indexable_page_has_canonical_and_preview_tags():
    for page in sync_site_shell.PAGES:
        html = (SITE / page).read_text()
        if page in sync_site_shell.NOINDEX:
            assert 'name="robots" content="noindex"' in html and "og:image" not in html, page
            continue
        assert '<meta property="og:image" content="' in html and "/img/og.png" in html, page
        assert 'name="twitter:card" content="summary_large_image"' in html, page
        assert '<meta name="description" content="' in html, page
        if page in sync_site_shell.CANONICAL:
            assert f'<link rel="canonical" href="{sync_site_shell.origin()}' in html, page
    assert (SITE / "img" / "og.png").stat().st_size > 10_000
    assert "rel = 'canonical'" in (SITE / "companies" / "page" / "page.js").read_text()


def test_static_files_are_cached_and_pages_revalidated(client):
    css = client.get("/shell/shell.css")
    assert css.headers["cache-control"].startswith("public, max-age=3600") and css.headers["etag"]
    assert client.get("/img/og.png").headers["cache-control"].startswith("public, max-age=")
    assert client.get("/developers/").headers["cache-control"] == "no-cache"
    assert client.get("/v1/public/plans").headers["cache-control"].startswith("public, max-age=")
    assert "cache-control" not in client.get("/healthz").headers


def test_responses_are_compressed_and_the_home_page_stays_in_budget(client):
    r = client.get("/", headers={"Accept-Encoding": "gzip"})
    assert r.headers.get("content-encoding") == "gzip"
    import gzip

    raw = (SITE / "index.html").read_bytes()
    assert len(gzip.compress(raw)) < 40_000, "home page over its 40 KB compressed budget"
    for img in (SITE / "img").glob("*.jpg"):
        assert img.stat().st_size < 250_000, img.name  # sized for how large they are shown


def test_cache_policy_unit():
    from app.main import cache_policy

    assert cache_policy("/v1/companies", "application/json") is None
    assert cache_policy("/mcp", "application/json") is None
    assert cache_policy("/chat.js", "text/javascript").startswith("public, max-age=3600")
    assert cache_policy("/IMG/X.JPG", "image/jpeg").startswith("public")
    assert cache_policy("/status/", "text/html; charset=utf-8") == "no-cache"
    assert cache_policy("/llms.txt", "text/plain") is None


def test_draft_legal_pages_are_linked_from_every_footer(client):
    needles = {
        "terms": "not investment",
        "privacy": "prv_session",
        "acceptable-use": "rate limits",
        "data-sources": "GDELT Project",
    }
    for slug, needle in needles.items():
        r = client.get(f"/legal/{slug}/")
        assert r.status_code == 200 and "pending legal review" in r.text, slug
        assert needle in r.text.lower() or needle in r.text, (slug, needle)
        canonical = f'<link rel="canonical" href="{sync_site_shell.origin()}/legal/{slug}/">'
        assert canonical in r.text, slug
    footer = (SITE / "shell" / "footer.html").read_text()
    for slug in ("terms", "privacy", "acceptable-use", "data-sources"):
        assert f'href="/legal/{slug}/"' in footer
    assert "/legal/privacy/" in client.get("/sitemap.xml").text


def test_developer_docs_cover_the_explorer_endpoints_and_watchlist_limits(client):
    """Tonight's endpoints are documented on /developers/ and in llms.txt, and the watchlist limits
    shown there are the plans' own (app/core/plans.py), so a plan change fails here until the docs
    follow."""
    import json
    import re

    from app.core.plans import PLANS

    html = client.get("/developers/").text
    llms = client.get("/llms.txt").text
    for path in ("/overview", "/statements/", "/timeline", "/v1/watchlists"):
        assert path in html and path in llms, path
    for anchor in ("overview", "statements", "timeline", "watchlists"):
        assert f'id="{anchor}"' in html and f'href="#{anchor}"' in html, anchor
    table = html.split('id="watchlist-limits"', 1)[1].split("</table>", 1)[0]
    shown = {}
    for label, lists, cos, cols in re.findall(
        r"<tr><td>([^<]+)</td><td>(\d+)</td><td>(\d+)</td><td>(\d+)</td></tr>", table
    ):
        for name in re.split(r", | and ", label):
            shown[name.strip().lower()] = (int(lists), int(cos), int(cols))
    public = [p["name"] for p in json.loads(Path("site/plans.json").read_text())["data"]]
    assert public
    for name in public:
        plan = PLANS[name]
        want = (plan.max_watchlists, plan.max_watchlist_companies, plan.max_watchlist_columns)
        assert shown.get(name) == want, (name, shown.get(name), want)


def test_developer_docs_cover_the_24_nov_endpoints_with_their_labels():
    """Each endpoint added on 24 Nov has a section with an example, the labels it must carry and its
    error reasons; examples link only to sec.gov/Archives and never show a CUSIP."""
    import re

    page = (SITE / "developers" / "index.html").read_text()
    llms = (SITE / "llms.txt").read_text()
    for path in ("/v1/companies/{cik}/executive-pay", "/v1/companies/{cik}/insider-plans",
                 "/v1/companies/{cik}/changes", "/v1/filings/{accession}/changes",
                 "/v1/companies/{cik}/calendar", "/v1/watchlists/{id}/calendar", "/v1/calendar?ciks=",
                 "/v1/companies/{cik}/comment-letters", "/v1/companies/{cik}/corporate-tree",
                 "/v1/private-raises"):
        assert path in page, path
        assert path.split("?")[0] in llms, path
    for words in ("as disclosed in the proxy", "self-reported by the issuer on Form D; amounts as filed",
                  "<strong>derived</strong>", "changes_not_available", "not_read", "prior_not_read",
                  "not_split", "include_suspect", "exclude_industry", "min_sold"):
        assert words in page, words
    for section in ("executive-pay", "insider-plans", "changes", "calendar", "comment-letters",
                    "corporate-tree", "private-raises"):
        assert f'href="#{section}"' in page and f'<section id="{section}"' in page, section
    new = page[page.index('<section id="executive-pay"'):page.index('<section id="ipos"')]
    urls = re.findall(r"https?://[^\"\s<]+", new)
    assert urls and all(u.startswith("https://www.sec.gov/Archives/") for u in urls), urls[:5]
    assert "cusip" not in new.lower()
