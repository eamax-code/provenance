"""The brand (Trace, chosen 24 Nov 2026; guide in docs/brand.md) lives in one place, site/shell/.

The marker yellow is a fill behind ink and the highlight on a figure's provenance moment; it is never a
figure's own colour (scripts/ui_checks/check.mjs checks the rendered pages) and never means up or down.
Warnings are orange so they never meet the marker. A change of colour or mark is a change in site/shell/.
"""

from __future__ import annotations

import colorsys
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import sync_site_shell  # noqa: E402

SITE = sync_site_shell.SITE
SHELL = SITE / "shell"
BRAND_HEXES = ("#f3e04c", "#eed43a", "#6b5d00", "#5f5200")  # marker, ledger marker, marker deep (light, ledger)
THEMES = ("", '[data-theme="light"]', '[data-theme="ledger"]', '[data-theme="terminal"]')


def _site_files():
    for path in SITE.rglob("*"):
        if path.suffix in {".css", ".js", ".html", ".svg"} and "poc" not in path.parts and "vendor" not in path.parts:
            yield path


def _theme_tokens() -> dict[str, dict[str, str]]:
    css = (SHELL / "shell.css").read_text()
    out = {}
    for theme in THEMES:
        block = re.search(r":root" + re.escape(theme) + r" \{(.*?)\n\}", css, re.S).group(1)
        out[theme or "dark"] = dict(re.findall(r"(--[a-z0-9-]+): (#[0-9a-f]{6})", block))
    return out


def _hue(hex_: str) -> float:
    r, g, b = (int(hex_[i : i + 2], 16) / 255 for i in (1, 3, 5))
    return colorsys.rgb_to_hsv(r, g, b)[0] * 360


def test_brand_colours_are_defined_only_in_the_shell():
    found = [
        f"{p.relative_to(SITE)}: {h}"
        for p in _site_files()
        if SHELL not in p.parents
        for h in BRAND_HEXES
        if h in p.read_text(encoding="utf-8").lower()
    ]
    assert not found, "brand colours belong in site/shell/ as tokens: " + "; ".join(found)


def test_every_theme_defines_the_brand_tokens_and_keeps_warn_away_from_the_marker():
    for theme, t in _theme_tokens().items():
        for name in ("--accent", "--accent-hi", "--accent-text", "--accent-ink", "--marker", "--marker-ink", "--mark", "--warn"):
            assert name in t, f"{theme} has no {name}"
        # orange, not amber: the warn hue sits well below the marker's yellow (about 54 degrees)
        assert _hue(t["--warn"]) <= 30 and _hue(t["--marker"]) >= 48, f"{theme}: --warn {t['--warn']} is near the marker"
        assert t["--good"] != t["--marker"] and t["--bad"] != t["--marker"], f"{theme}: yellow never means up or down"


def test_the_marker_is_only_the_highlight():
    # --marker paints selection and the hover highlight behind a figure link, always with --marker-ink on it
    uses = []
    for p in _site_files():
        for m in re.finditer(r"[^{}]*\{[^}]*var\(--marker\)[^}]*\}", p.read_text(encoding="utf-8")):
            uses.append((p.relative_to(SITE).as_posix(), m.group(0).strip()))
    assert uses, "the highlight rule is missing"
    for where, rule in uses:
        assert re.search(r"background: var\(--marker\)", rule) and "color: var(--marker-ink)" in rule, f"{where}: {rule[:120]}"
        assert re.search(r"color: var\(--marker\)", rule) is None, f"{where}: the marker is never a text colour"


def test_data_marks_are_never_the_accent():
    # a chart's latest bar, end dot or own row is --data-hi (a neutral); yellow reaches a data mark only as the
    # highlight on hover or when it opens its filing (background: var(--marker))
    rule = re.compile(r"([^{}]*)\{([^}]*)\}")
    found = []
    for p in _site_files():
        if p.suffix not in {".css", ".html"}:
            continue
        for sel, body in rule.findall(p.read_text(encoding="utf-8")):
            if re.search(r"chart|spark|\.bar|\.col|bar-h|ui-bars|pp-tsr|k-tsr", sel) and ":hover" not in sel and ":focus" not in sel:
                if re.search(r"(fill|stroke|background)(-color)?: ?var\(--(accent|accent-hi|marker)\)", body):
                    found.append(f"{p.relative_to(SITE)}: {sel.strip()[:60]}")
    assert not found, "data marks use --data-hi, not the accent: " + "; ".join(found)


def test_the_provenance_moment_respects_reduced_motion():
    css = (SITE / "app" / "app.css").read_text()
    assert "@keyframes prov-sweep" in css and "@keyframes prov-reveal" in css and "@keyframes prov-draw" in css
    assert "'data-t': text" in (SITE / "prov-card.js").read_text(), "the reveal copies the figure's own text"
    rm = css[css.index("@media (prefers-reduced-motion: reduce) {\n  .door"):]
    rm = rm[: rm.index("\n}") + 2]
    for sel in (".door[aria-expanded=\"true\"]", ".door[aria-expanded=\"true\"]::after", ".prov-v b::after", ".prov-lead path", ".prov-lead circle"):
        assert sel in rm, f"reduced motion must stop {sel}"
    assert "animation: none" in rm and "stroke-dashoffset: 0" in rm
    assert ".door:focus-visible" in css, "keyboard focus gets the same hint as hover"


def test_every_page_carries_the_brand_icons_and_the_logo():
    for name in ("favicon.svg", "favicon-32.png", "apple-touch-icon.png", "mark.svg", "seal.js"):
        assert (SHELL / name).is_file(), name
    assert (SITE / "favicon.ico").is_file()
    header = (SHELL / "header.html").read_text()
    assert 'aria-label="Provenance home"' in header and 'aria-hidden="true"' in header
    for page in sync_site_shell.PAGES:
        html = (SITE / page).read_text()
        assert '<link rel="icon" href="/shell/favicon.svg" type="image/svg+xml">' in html, page
        assert '<link rel="apple-touch-icon" href="/shell/apple-touch-icon.png">' in html, page
        assert "data:image/svg+xml" not in html, f"{page} keeps an old inline icon"


def test_the_seal_is_decorative():
    js = (SHELL / "seal.js").read_text()
    assert "'aria-hidden': 'true'" in js and "focusable: 'false'" in js
    assert "<text" not in js, "the seal carries no letters or figures"
