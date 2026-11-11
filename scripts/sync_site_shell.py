"""Write the shared header, footer and head links into every page of the static site (GH #11).

The parts live once in ``site/shell/``; each page marks where they go with
``<!-- shell:NAME -->`` and ``<!-- /shell:NAME -->``. Run this after changing a part;
``--check`` exits non-zero when a page is out of date (the tests call ``out_of_date``).
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

SITE = Path(__file__).resolve().parent.parent / "site"
SHELL = SITE / "shell"
HEAD = '<link rel="stylesheet" href="/shell/shell.css">\n<script src="/shell/shell.js"></script>'
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
)


def parts() -> dict[str, str]:
    return {
        "head": HEAD,
        "theme": (SHELL / "theme-head.html").read_text().strip(),
        "header": (SHELL / "header.html").read_text().strip(),
        "footer": (SHELL / "footer.html").read_text().strip(),
    }


def render(text: str, found: dict[str, str]) -> str:
    for name, body in found.items():
        pattern = re.compile(rf"<!-- shell:{name} -->.*?<!-- /shell:{name} -->", re.S)
        block = f"<!-- shell:{name} -->\n{body}\n<!-- /shell:{name} -->"
        text = pattern.sub(lambda m, b=block: b, text)
    return text


def out_of_date() -> list[str]:
    found = parts()
    return [p for p in PAGES if render((SITE / p).read_text(), found) != (SITE / p).read_text()]


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
        after = render(before, found)
        if after != before:
            path.write_text(after)
            print(f"updated site/{p}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
