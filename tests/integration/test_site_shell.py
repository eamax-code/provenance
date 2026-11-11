"""One header, footer and palette on every page; the reader's theme in chat and the Explorer
(GH #11, #12)."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import sync_site_shell  # noqa: E402

PUBLIC = ("/", "/companies/", "/companies/0000320193", "/listings/", "/status/", "/playground/")


def test_every_page_carries_the_current_shell():
    assert sync_site_shell.out_of_date() == [], "run scripts/sync_site_shell.py"
    for page in sync_site_shell.PAGES:
        html = (sync_site_shell.SITE / page).read_text()
        assert '<link rel="stylesheet" href="/shell/shell.css">' in html, page
        # the shell's palette is the only one: page stylesheets load after it and add no theme
        assert html.index("/shell/shell.css") < html.index("</head>"), page


def test_public_pages_share_the_header_and_footer_and_stay_dark(client):
    for path in (*PUBLIC, "/app/"):
        html = client.get(path).text
        assert 'class="site-bar"' in html and 'class="site-foot"' in html, path
        assert "not affiliated" in html.lower(), path
    for path in PUBLIC:
        html = client.get(path).text
        assert "data-theme" not in html and "prv-theme" not in html, path  # never the reader's
    client.cookies.clear()
    for path in ("/chat/", "/app/"):
        assert "localStorage.getItem('prv-theme')" in client.get(path).text, path
    css = client.get("/shell/shell.css").text
    for theme in ("light", "ledger", "terminal"):
        assert f':root[data-theme="{theme}"]' in css
    js = client.get("/shell/shell.js").text
    assert "/v1/developer/profile" in js and "/v1/stats" in js


def test_profile_keeps_the_theme_with_the_key(client, auth):
    r = client.get("/v1/developer/profile", headers=auth)
    assert r.status_code == 200, r.text
    assert r.json()["ui_theme"] == "dark" and r.json()["plan"]
    r = client.patch("/v1/developer/profile", headers=auth, json={"ui_theme": "terminal"})
    assert r.status_code == 200 and r.json()["ui_theme"] == "terminal"
    assert client.get("/v1/developer/profile", headers=auth).json()["ui_theme"] == "terminal"
    bad = client.patch("/v1/developer/profile", headers=auth, json={"ui_theme": "neon"})
    assert bad.status_code == 422
    assert client.get("/v1/developer/profile", headers={"X-API-Key": "demo"}).status_code == 401
    r = client.patch("/v1/developer/profile", headers=auth, json={"ui_theme": "dark"})
    assert r.json()["ui_theme"] == "dark"
