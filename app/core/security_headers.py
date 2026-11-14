"""Security headers on every response (GH #18).

The content security policy allows scripts from this site only, plus the exact inline scripts
the site's pages carry, by hash. The hashes are read from the pages when the app starts, so an
injected inline script never runs and a changed page needs no edit here. Fonts come from Google
Fonts; nothing else is loaded from another origin.
"""

from __future__ import annotations

import base64
import hashlib
import re
from pathlib import Path

from starlette.types import ASGIApp, Message, Receive, Scope, Send

INLINE_SCRIPT = re.compile(r"<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>", re.S)
# Prototype pages are not served in production and load their own CDN scripts.
EXEMPT_PREFIXES = ("/poc/",)


def inline_script_hashes(site: Path | None) -> list[str]:
    """CSP source expressions for every inline script in the site's pages."""
    if site is None or not site.is_dir():
        return []
    found: set[str] = set()
    for page in site.rglob("*.html"):
        if "poc" in page.relative_to(site).parts:
            continue
        for body in INLINE_SCRIPT.findall(page.read_text(encoding="utf-8")):
            digest = hashlib.sha256(body.encode("utf-8")).digest()
            found.add(f"'sha256-{base64.b64encode(digest).decode()}'")
    return sorted(found)


def content_security_policy(script_hashes: list[str]) -> str:
    directives = {
        "default-src": ["'self'"],
        "script-src": ["'self'", *script_hashes],
        # style attributes in the markup (animation delays, widths) need 'unsafe-inline'
        "style-src": ["'self'", "'unsafe-inline'", "https://fonts.googleapis.com"],
        "font-src": ["'self'", "https://fonts.gstatic.com"],
        "img-src": ["'self'", "data:"],
        "connect-src": ["'self'"],
        "object-src": ["'none'"],
        "base-uri": ["'self'"],
        "form-action": ["'self'"],
        "frame-ancestors": ["'none'"],
    }
    return "; ".join(f"{name} {' '.join(values)}" for name, values in directives.items())


class SecurityHeadersMiddleware:
    """Pure ASGI, so streamed responses (the event stream) pass through untouched."""

    def __init__(self, app: ASGIApp, site: Path | None = None, hsts: bool = False) -> None:
        self.app = app
        csp = content_security_policy(inline_script_hashes(site))
        self.headers = [
            (b"x-content-type-options", b"nosniff"),
            (b"referrer-policy", b"strict-origin-when-cross-origin"),
            (b"x-frame-options", b"DENY"),
            (b"cross-origin-opener-policy", b"same-origin"),
            (b"permissions-policy", b"camera=(), microphone=(), geolocation=(), payment=()"),
        ]
        self.csp = (b"content-security-policy", csp.encode())
        if hsts:  # only behind HTTPS; a browser remembers it for a year
            self.headers.append(
                (b"strict-transport-security", b"max-age=31536000; includeSubDomains")
            )

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        exempt = scope.get("path", "").startswith(EXEMPT_PREFIXES)

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                present = {name.lower() for name, _ in headers}
                extra = self.headers if exempt else [*self.headers, self.csp]
                headers += [(n, v) for n, v in extra if n not in present]
                message["headers"] = headers
            await send(message)

        await self.app(scope, receive, send_with_headers)
