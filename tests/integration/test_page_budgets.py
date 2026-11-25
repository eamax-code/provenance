"""Page weight budgets and stale copy (design pass, 2026-11-22).

The heavy pages keep a compressed weight budget like the home page's 40 KB, set just above their
size when added: what the page itself ships (HTML, its own CSS and JS), not the shared shell or the
data it fetches. scripts/ui_checks/perf.mjs measures the full transfer and LCP in a throttled
browser; this test keeps the part that grows with code from creeping up unnoticed.

Counts in the copy (metrics, companies, figures) must come from data: a sentence like "the five
financial figures" went stale when coverage grew, so the words are banned outside the changelog.
"""

from __future__ import annotations

import gzip
import re
from pathlib import Path

SITE = Path(__file__).resolve().parents[2] / "site"

# page: (files it ships, budget in bytes compressed); measured 2026-11-22: company 24.8 KB,
# chat 22.6 KB, ipos 10.3 KB, shell 9.1 KB. The company page grew to 28.2 KB the same day with
# three agreed sections (13F ownership, successor registrants, segments); the sections below the
# first screens then moved to company-lower.js, loaded as they come near the screen, and the
# first-load budget went back to 28 KB. company-lower.js has its own budget, raised to 8 KB when the
# identity block (with the LEI match note) moved there from the first load (26.6 KB after), and to
# 8.5 KB with 13F share classes and ADRs (8.0 KB after trimming its comments).
BUDGETS = {
    "company page": (
        ["companies/page/snapshot.html", "companies/page/page.css", "companies/page/page.js",
         "companies/page/company.js", "shell/seal.js"],
        28_000,
    ),
    # the company seal (shell/seal.js, brand B-3, 24 Nov) is counted with each page that loads it
    "company page, lower sections (loaded later)": (["companies/page/company-lower.js"], 8_500),
    # the figure view (issue #10) left the first load on 24 Nov: page.js loads it on first open
    "company page, figure view (loaded on open)": (["companies/page/figure-view.js"], 5_500),
    # chat: 25.3 KB on 23 Nov with C-01/C-02 (figure chips, how, hand-off); 27.3 KB on 24 Nov with C-08
    # (CSV per table, a link per answer, a visible Copy), so the budget went to 28 KB
    # B-G1 (25 Nov): chat and ipos raised to their real first loads, app/app.css counted (no new
    # code): chat 41.0 KB with it, ipos 24.3 KB
    "chat": (["chat/index.html", "app/app.css", "chat.css", "chat.js"], 42_000),
    "ipos": (["ipos/index.html", "app/app.css", "ipos/ipos.css", "ipos/ipos.js"], 25_500),
    # the Explorer (/app/): its page, CSS and every script it loads except the shared shell. 133.4 KB on
    # 24 Nov after the window's new views (People, Calendar, What changed, letters and tree, What's new,
    # private raises); the budget is that plus about 10% so it stops growing unnoticed. X-22 (24 Nov): the
    # connections graph (graph.js) loads only when Connections opens, so it left this first-load list
    # (135.9 KB before, 121.2 KB after) for its own budget below.
    "explorer": (["app/index.html", "app/app.css", "app/console.js", "app/listings.js", "app/app.js",
                  "prov-card.js", "app/calendar.js", "app/people.js", "app/changes.js",
                  "app/records.js", "app/whatsnew.js", "app/workspace.js", "app/raises.js",
                  "app/screener.js", "app/watchlists.js", "shell/seal.js"], 147_000),
    "explorer, connections graph (loaded when the tab opens)": (["app/graph.js"], 16_500),
    # Search inside filings (Q-01, 24 Nov): 9.2 KB when added
    "search": (["search/index.html", "search/search.css", "search/search.js"], 10_500),
    "insiders": (["insiders/index.html", "insiders/insiders.css", "insiders/insiders.js"], 12_800),
    # Q-02 fund managers (25 Nov, PM-approved): about 8.8 KB and 10.5 KB gzipped at launch
    "managers": (["managers/index.html", "managers/managers.css", "managers/managers.js"], 10_000),
    "manager": (["managers/manager.html", "managers/managers.css", "managers/manager.js"], 11_000),
    # Q-04 dividends block, a shared lazy module (25 Nov): 4.1 KB gzipped at launch
    "dividends": (["app/dividends.js"], 5_000),
    # Q-07 activist stakes (25 Nov, PM-approved): the Explorer's lazy module 4.8 KB, the page 13.2 KB
    "activists module": (["app/activists.js"], 5_000),
    "activists": (["activists/index.html", "activists/activists.css", "activists/activists.js",
                   "app/activists.js"], 14_000),
    "shell": (["shell/shell.css", "shell/shell.js"], 10_500),
    # the public pages' shared stylesheet (B-G1): 1.7 KB
    "public.css": (["public.css"], 2_000),
}


# lines every page loads, counted once on their own (B-G1)
SHARED = ("shell", "public.css")


def _first_load(page: str) -> set[str]:
    """Same-origin scripts and stylesheets a page's HTML loads on first load, as site paths."""
    from html.parser import HTMLParser
    from posixpath import dirname, join, normpath

    found: set[str] = set()
    base = "/" + dirname(page) + "/"

    class P(HTMLParser):
        def handle_starttag(self, tag, attrs):
            a = dict(attrs)
            ref = a.get("src") if tag == "script" else (
                a.get("href") if tag == "link" and "stylesheet" in (a.get("rel") or "").split()
                else None)  # fmt: skip
            if not ref or re.match(r"^(?:[a-z]+:)?//", ref) or ref.startswith(("data:", "#")):
                return
            path = ref.split("?", 1)[0].split("#", 1)[0]
            found.add(normpath(path if path.startswith("/") else join(base, path)).lstrip("/"))

    P().feed((SITE / page).read_text(encoding="utf-8"))
    return found


def test_every_file_a_page_loads_first_is_in_its_budget():
    """B-G1: a budgeted page's first-load scripts and stylesheets are each in its own list or in a
    shared line, so a file added to the HTML cannot ship outside every budget (chat loaded
    prov-card.js and app/app.css, about 16 KB, unlisted)."""
    shared = {f for name in SHARED for f in BUDGETS[name][0]}
    missing = []
    for name, (files, _budget) in BUDGETS.items():
        for page in (f for f in files if f.endswith(".html")):
            for f in sorted(_first_load(page) - set(files) - shared):
                if (SITE / f).exists():
                    missing.append(f"{name}: {f}")
    assert not missing, "loaded on first load but in no budget: " + "; ".join(missing)


def test_heavy_pages_stay_in_their_compressed_budget():
    for name, (files, budget) in BUDGETS.items():
        size = sum(len(gzip.compress((SITE / f).read_bytes())) for f in files)
        assert size < budget, f"{name} is {size} bytes compressed, over its {budget} budget"


_N = r"\b(?:three|four|five|six|seven|eight|nine|ten|twenty|thirty|forty|\d+)\s+"
# "five metrics", "32 normalized metrics", "the five financial figures"; not "two reported figures"
# (how a ratio is defined) or a dated example such as "1,332 figures nobody had yet"
STALE_COUNT = re.compile(
    _N + r"(?:normali[sz]ed\s+|financial\s+)?metrics\b|" + _N + r"(?:normali[sz]ed\s+)?financial\s+figures\b",
    re.I,
)
# dated changelog entries describe history; example strings are not claims about coverage
ALLOWED = ("changelog/index.html",)


def test_site_copy_never_hard_codes_how_many_metrics():
    found = []
    for path in SITE.rglob("*"):
        if path.suffix not in {".html", ".js", ".txt"} or "poc" in path.parts or "vendor" in path.parts:
            continue
        rel = path.relative_to(SITE).as_posix()
        if rel in ALLOWED:
            continue
        for m in STALE_COUNT.finditer(path.read_text(encoding="utf-8")):
            found.append(f"{rel}: {m.group(0)!r}")
    assert not found, "counts must come from data (stats, plans, coverage): " + "; ".join(found)


def test_coverage_mapping_exceptions_sentence_matches_the_csv():
    # /coverage/ states the mapping exceptions in one static sentence; it must match the reviewed list
    import csv

    text = (SITE.parent / "app" / "data" / "mapping_exceptions.csv").read_text(encoding="utf-8")
    rows = list(csv.DictReader(text.splitlines()))
    figures, companies = sum(int(r["rows"]) for r in rows), len({r["cik"] for r in rows})
    versions = sorted({r["mapping_version"] for r in rows})
    html = (SITE / "coverage" / "index.html").read_text(encoding="utf-8")
    m = re.search(r'id="cov-map-exceptions">([\d,]+) figures at (\d+) compan\w+ stay on mapping ([\d.]+)', html)
    assert m, "the mapping-exceptions sentence is missing from /coverage/"
    assert (int(m.group(1).replace(",", "")), int(m.group(2)), [m.group(3)]) == (figures, companies, versions)


def test_the_explorer_budget_counts_every_script_the_page_loads():
    html = (SITE / "app" / "index.html").read_text()
    loaded = {m.lstrip("/") for m in re.findall(r'(?:src|href)="(/[^"]+\.(?:js|css))"', html)
              if not m.startswith("/shell/")}
    assert loaded <= set(BUDGETS["explorer"][0]), sorted(loaded - set(BUDGETS["explorer"][0]))
