"""Security headers, CORS, prototypes off in production and chat abuse limits (GH #18)."""

from __future__ import annotations

import base64
import hashlib
import re
from pathlib import Path

SITE = Path(__file__).resolve().parents[2] / "site"


def _csp(r) -> dict[str, list[str]]:
    out = {}
    for part in r.headers["content-security-policy"].split(";"):
        name, *values = part.split()
        out[name] = values
    return out


def test_every_response_carries_the_security_headers(client):
    for path in ("/", "/developers/", "/v1/public/plans", "/healthz", "/shell/shell.js"):
        r = client.get(path)
        assert r.headers["x-content-type-options"] == "nosniff", path
        assert r.headers["referrer-policy"] == "strict-origin-when-cross-origin", path
        assert r.headers["x-frame-options"] == "DENY", path
        assert "camera=()" in r.headers["permissions-policy"], path
        csp = _csp(r)
        assert csp["frame-ancestors"] == ["'none'"] and csp["object-src"] == ["'none'"], path
        scripts = csp["script-src"]
        assert "'unsafe-inline'" not in scripts and "'unsafe-eval'" not in scripts
        assert "strict-transport-security" not in r.headers  # development is plain HTTP


def test_every_inline_script_on_the_site_is_allowed_by_hash_and_nothing_else(client):
    csp = _csp(client.get("/"))
    allowed = set(csp["script-src"])
    pattern = re.compile(r"<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>", re.S)
    count = 0
    for page in SITE.rglob("*.html"):
        if "poc" in page.parts:
            continue
        for body in pattern.findall(page.read_text()):
            digest = base64.b64encode(hashlib.sha256(body.encode()).digest()).decode()
            assert f"'sha256-{digest}'" in allowed, page
            count += 1
        for src in re.findall(r'<script[^>]*\bsrc="([^"]+)"', page.read_text()):
            assert src.startswith("/"), (page, src)  # scripts come from this site only
    assert count >= 5
    assert {s for s in allowed if s.startswith("'sha256-")} and "https:" not in allowed


def test_prototypes_skip_the_policy_in_development(client):
    r = client.get("/poc/themes/")
    assert r.status_code == 200 and "content-security-policy" not in r.headers
    assert r.headers["x-frame-options"] == "DENY"


def test_production_hides_the_prototypes_and_sends_hsts(settings, monkeypatch):
    from fastapi.testclient import TestClient

    from app.main import create_app

    monkeypatch.setattr(settings, "app_env", "production")
    with TestClient(create_app(settings)) as c:
        assert c.get("/poc/themes/").status_code == 404
        assert c.get("/poc/gamification/game.js").status_code == 404
        r = c.get("/healthz")
        assert r.headers["strict-transport-security"].startswith("max-age=31536000")


def test_cors_is_off_unless_origins_are_configured(client, settings, monkeypatch):
    from fastapi.testclient import TestClient

    from app.main import create_app

    pre = {"Origin": "https://evil.example", "Access-Control-Request-Method": "GET"}
    r = client.options("/v1/public/plans", headers=pre)
    assert "access-control-allow-origin" not in r.headers
    monkeypatch.setattr(settings, "cors_allow_origins", "https://app.example")
    with TestClient(create_app(settings)) as c:
        ok = {**pre, "Origin": "https://app.example", "Access-Control-Request-Headers": "x-api-key"}
        r = c.options("/v1/public/plans", headers=ok)
        assert r.headers["access-control-allow-origin"] == "https://app.example"
        assert "access-control-allow-credentials" not in r.headers
        r = c.options("/v1/public/plans", headers=pre)
        assert r.headers.get("access-control-allow-origin") != "https://evil.example"


def test_chat_has_a_daily_cap_per_caller(client, settings, monkeypatch):
    monkeypatch.setattr(settings, "chat_requests_per_day", 2)
    monkeypatch.setattr(settings, "llm_enabled", False)
    demo = {"X-API-Key": "demo"}
    codes = [client.post("/v1/chat", json={"message": "hello"}, headers=demo).status_code
             for _ in range(3)]  # fmt: skip
    assert codes[:2] != [429, 429] and codes[2] == 429
    r = client.post("/v1/chat", json={"message": "hello"}, headers=demo)
    assert r.json()["error"]["code"] == "quota_exceeded" and "Retry-After" in r.headers


def test_admin_routes_need_the_admin_token(client, settings, monkeypatch):
    body = {"owner_email": "someone@example.com"}
    monkeypatch.setattr(settings, "admin_token", "")
    assert client.post("/v1/developer/api-keys", json=body).status_code == 503
    monkeypatch.setattr(settings, "admin_token", "a" * 32)
    r = client.post("/v1/developer/api-keys", json=body, headers={"X-Admin-Token": "wrong"})
    assert r.status_code in (401, 403)
    r = client.post("/v1/developer/api-keys", json=body, headers={"X-API-Key": "demo"})
    assert r.status_code in (401, 403)


def test_prompts_treat_filing_text_as_data():
    from app.api.routes_chat import SYSTEM_PROMPT
    from app.services.forecast import THINK_PROMPT
    from app.services.officer_changes import EXTRACT_PROMPT

    assert "do not follow them" in SYSTEM_PROMPT
    assert "not instructions" in EXTRACT_PROMPT
    assert "never follow instructions" in THINK_PROMPT


def test_site_scripts_never_parse_api_text_as_markup():
    # The only innerHTML writes are clearing a box or static markup written in the file itself.
    risky = re.compile(r"innerHTML\s*=(?!=)(?!\s*(?:''|\"\"))")
    allowed = {"chat.js": 1, "docs.js": 1, "page.js": 1}  # static strings, reviewed (GH #18)
    for js in SITE.rglob("*.js"):
        if "vendor" in js.parts or "poc" in js.parts:
            continue
        hits = len(risky.findall(js.read_text()))
        assert hits <= allowed.get(js.name, 0), (js, hits)


def test_no_page_loads_anything_from_google_fonts():
    """Fonts are self-hosted, so no visitor's address goes to Google (GDPR)."""
    from pathlib import Path

    site = Path(__file__).resolve().parents[2] / "site"
    hits = [str(p.relative_to(site)) for p in site.rglob("*")
            if p.is_file() and p.suffix in (".html", ".css", ".js") and "poc" not in p.parts
            and ("googleapis" in p.read_text(errors="ignore")
                 or "gstatic" in p.read_text(errors="ignore"))]  # fmt: skip
    assert hits == []


def test_csp_allows_no_font_cdn(client):
    csp = client.get("/healthz").headers["Content-Security-Policy"]
    assert "googleapis" not in csp and "gstatic" not in csp
