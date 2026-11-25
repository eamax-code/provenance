"""Write the shared header, footer and head links into every page of the static site (GH #11).

The parts live once in ``site/shell/``; each page marks where they go with
``<!-- shell:NAME -->`` and ``<!-- /shell:NAME -->``. Run this after changing a part;
``--check`` exits non-zero when a page is out of date (the tests call ``out_of_date``).
"""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
from pathlib import Path

SITE = Path(__file__).resolve().parent.parent / "site"
SHELL = SITE / "shell"
# the brand's icons live with the tokens in site/shell/ (Trace, 24 Nov 2026): an SVG that follows the
# reader's light or dark scheme, a PNG tile for browsers without SVG icons, the home-screen icon
ICONS = (
    '<link rel="icon" href="/shell/favicon.svg" type="image/svg+xml">\n'
    '<link rel="icon" href="/shell/favicon-32.png" sizes="32x32" type="image/png">\n'
    '<link rel="apple-touch-icon" href="/shell/apple-touch-icon.png">\n'
)
HEAD = ICONS + '<link rel="stylesheet" href="/shell/shell.css">\n<script src="/shell/shell.js"></script>'
PAGES = (
    "index.html",
    "companies/index.html",
    "companies/page/snapshot.html",
    "companies/page/report.html",
    "companies/page/dossier.html",
    "listings/index.html",
    "status/index.html",
    "playground/index.html",
    "app/index.html",
    "chat/index.html",
    "developers/index.html",
    "docs/index.html",
    "changelog/index.html",
    "not-found.html",
    "error.html",
    "account/index.html",
    "account/verify/index.html",
    "contact/index.html",
    "ipos/index.html",
    "coverage/index.html",
    "search/index.html",
    "insiders/index.html",
    "managers/index.html",
    "managers/manager.html",
    "filings/section.html",
    "activists/index.html",
    "docs/flags/index.html",
    "legal/terms/index.html",
    "legal/privacy/index.html",
    "legal/acceptable-use/index.html",
    "legal/data-sources/index.html",
)


# The address each page is published at, for its canonical link (GH #21). Company layouts share
# one address per company (page.js sets theirs); the 404 and error pages are never indexed.
CANONICAL = {
    "index.html": "/",
    "companies/index.html": "/companies/",
    "listings/index.html": "/listings/",
    "status/index.html": "/status/",
    "playground/index.html": "/playground/",
    "app/index.html": "/app/",
    "chat/index.html": "/chat/",
    "developers/index.html": "/developers/",
    "docs/index.html": "/docs/",
    "changelog/index.html": "/changelog/",
    "account/index.html": "/account/",
    "contact/index.html": "/contact/",
    "ipos/index.html": "/ipos/",
    "coverage/index.html": "/coverage/",
    "search/index.html": "/search/",
    "insiders/index.html": "/insiders/",
    "managers/index.html": "/managers/",
    "activists/index.html": "/activists/",
    "docs/flags/index.html": "/docs/flags/",
    "legal/terms/index.html": "/legal/terms/",
    "legal/privacy/index.html": "/legal/privacy/",
    "legal/acceptable-use/index.html": "/legal/acceptable-use/",
    "legal/data-sources/index.html": "/legal/data-sources/",
}
NOINDEX = ("not-found.html", "error.html", "account/verify/index.html")
OG_IMAGE = "/img/og.png"


def origin() -> str:
    """The public origin from site/shell/site.json; empty until the domain is chosen (ticket 02)."""
    return json.loads((SHELL / "site.json").read_text()).get("origin", "").rstrip("/")


def meta(page: str, text: str) -> str | None:
    """Canonical link and link-preview tags, from the page's own title and description."""
    if page in NOINDEX:
        return None
    title = re.search(r"<title>(.*?)</title>", text, re.S)
    desc = re.search(r'<meta name="description" content="([^"]*)">', text)
    base = origin()
    og_title = html.escape(title.group(1).strip()) if title else "Provenance"
    lines = []
    if page in CANONICAL:
        lines.append(f'<link rel="canonical" href="{base}{CANONICAL[page]}">')
        lines.append(f'<meta property="og:url" content="{base}{CANONICAL[page]}">')
    lines += [
        '<meta property="og:type" content="website">',
        '<meta property="og:site_name" content="Provenance">',
        f'<meta property="og:title" content="{og_title}">',
        f'<meta property="og:description" content="{desc.group(1) if desc else ""}">',
        f'<meta property="og:image" content="{base}{OG_IMAGE}">',
        '<meta property="og:image:width" content="1200">',
        '<meta property="og:image:height" content="630">',
        '<meta property="og:image:alt" content="Provenance: every figure cites its SEC filing.">',
        '<meta name="twitter:card" content="summary_large_image">',
    ]
    return "\n".join(lines)


def parts() -> dict[str, str]:
    return {
        "head": HEAD,
        "theme": (SHELL / "theme-head.html").read_text().strip(),
        "header": (SHELL / "header.html").read_text().strip(),
        "footer": (SHELL / "footer.html").read_text().strip(),
        # the one MCP install line, so home and the developer guide never drift apart
        "mcp": (SHELL / "mcp.html").read_text().strip(),
    }


def render(text: str, found: dict[str, str], page: str | None = None) -> str:
    found = dict(found)
    if page is not None and (m := meta(page, text)) is not None:
        found["meta"] = m
    for name, body in found.items():
        pattern = re.compile(rf"<!-- shell:{name} -->.*?<!-- /shell:{name} -->", re.S)
        block = f"<!-- shell:{name} -->\n{body}\n<!-- /shell:{name} -->"
        text = pattern.sub(lambda m, b=block: b, text)
    return text


def out_of_date() -> list[str]:
    found = parts()
    return [p for p in PAGES if render((SITE / p).read_text(), found, p) != (SITE / p).read_text()]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true", help="report pages that are out of date")
    args = ap.parse_args()
    if args.check:
        stale = out_of_date()
        for p in stale:
            print(f"out of date: site/{p}")
        return 1 if stale else 0
    found = parts()
    for p in PAGES:
        path = SITE / p
        before = path.read_text()
        after = render(before, found, p)
        if after != before:
            path.write_text(after)
            print(f"updated site/{p}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
