# Brand: Trace

Chosen by the owner on 24 Nov 2026, from three directions (Hallmark, Accession, Trace). The direction cards and the working are in `provenance-review/brand/`; the guidelines kit (logo files, tokens, seal sheet) is in `provenance-review/brand/kit/`.

**The idea.** An analyst marks a figure in a 10-K and draws a leader to where it came from. The logo is that gesture: a chisel-tip highlight with the P knocked out, whose stem leaves the highlight and turns, as a leader does, to land on a dot (the source). The highlight is the brand's one moment: when a figure is marked, it is because you can follow it to its filing.

## Logo

- **Symbol:** the highlight, the P, the leader and the dot, on a 100-unit grid, in one colour (`site/shell/mark.svg`). There is no outline version and no gradient.
- **Wordmark:** `provenance`, lower case, Schibsted Grotesk 800, tracking −0.03em. The header draws the symbol at 1.45 times the wordmark's size, with a 0.42em gap.
- **Colour:** `--mark`: marker yellow on dark grounds (Dark, Terminal), and ink on light ones (Light, Ledger). It is never yellow on a light ground.
- **Clear space:** the dot's diameter on every side. **Minimum size:** 20 px for the symbol with the wordmark, and 16 px for the favicon mark.
- **Accessible name:** the header link is "Provenance home". The symbol is `aria-hidden`.
- **Don't:**
  - recolour the P or the dot separately;
  - add a tick, star, ring or "verified" mark;
  - put the symbol in a circle;
  - set the wordmark in capitals.

## Favicon and icons (all in `site/shell/`, linked by `scripts/sync_site_shell.py`)

- `favicon.svg`: only the highlight and the source dot, aligned to the 16 px pixel grid (the highlight is rows 1–8, the dot rows 11–15). It is ink in a light browser scheme and marker yellow in a dark one.
- `favicon-32.png` and `site/favicon.ico` (16 and 32): the marker mark on an ink tile, which reads on either tab colour.
- `apple-touch-icon.png` (180): the same tile, square, for iOS to mask.
- Check 16 px survival in a real browser tab on light and dark after any change. `logo_audit` is **hand-checked (tools blocked)** for now: the brand-identity scripts' Python dependencies could not be installed on this Mac. Nothing in the favicon is thinner than 1 px at 16 px.

## Colour (tokens in `site/shell/shell.css`, one place)

| Token | Dark | Light | Ledger | Terminal | Use |
|---|---|---|---|---|---|
| `--accent` | #f3e04c | #f3e04c | #eed43a | #f3e04c | fill behind ink: buttons, the one action |
| `--accent-ink` | #16181b | #16181b | #16181b | #0d1117 | text on `--accent` |
| `--accent-hi` | #f3e04c | #6b5d00 | #5f5200 | #f3e04c | the accent as a line: focus, selected tab, latest bar |
| `--accent-text` | #e7ebee | #6b5d00 | #5f5200 | #d6dde6 | link text: ink on dark grounds, olive on light ones |
| `--link-line` | #f3e04c | currentColor | currentColor | #f3e04c | the link underline: a marker underline on dark grounds |
| `--data-hi` | ink | ink | ink | ink | the marked data point: latest bar, end dot, own row. A neutral, never yellow |
| `--marker` / `--marker-ink` | #f3e04c / #16181b | #f3e04c / #16181b | #eed43a / #16181b | #f3e04c / #0d1117 | the highlight only |
| `--mark` | #f3e04c | #16181b | #1f1c17 | #f3e04c | the logo and the seal |
| `--warn` | #f0883e | #a34a07 | #9a4a12 | #f0883e | warnings: orange, never amber |

Rules, each checked by a test or the UI audit:

1. Yellow is spent sparingly. It is a fill behind ink (the primary button), the highlight, and a line on dark grounds (focus, the selected tab, the current nav item's underline, link underlines). On dark grounds links are ink with a marker underline. On light grounds the accent becomes marker deep (olive) as a line or as text (`tests/integration/test_brand.py`).
   - The current nav item is ink with an underline, never coloured text.
2. **The marker is never a figure's own colour, and never a data mark's.** It may only sit behind a figure as the highlight, with `--marker-ink` on it. That covers:
   - the hero card's figure, the one static use, because that card is a provenance card;
   - the hover on a figure link or a bar that opens its filing;
   - selection.

   The latest bar and end dots use `--data-hi`. `scripts/ui_checks/check.mjs` fails a figure or data mark in the marker yellow, whether it's text, a chart label, an SVG shape, an empty HTML bar, or a Chart.js dataset.
3. Yellow never means up or down. Changes stay `--good` and `--bad`, and only on flows.
4. `--warn` is orange, so a warning never meets the marker.
5. Brand hexes appear only in `site/shell/`. Pages read tokens (`test_brand_colours_are_defined_only_in_the_shell`).

## Type

- Schibsted Grotesk (display and the wordmark), IBM Plex Sans (reading, in Ledger and Terminal), IBM Plex Mono (figures in Terminal, code, accession numbers), and Newsreader 600 (Ledger headings).
- All are self-hosted under the SIL Open Font License. The licence files are in `site/fonts/`. The brand adds no font.

## The company seal

- Each company page and the Explorer's company header carry a small seal, drawn by `site/shell/seal.js` from the CIK. It is an open trace: a highlight chip, a leader with one to three square turns, and a dot. It is the logo's gesture at the size of a mark.
- It is **decorative**: `aria-hidden`, with no letters, no figures, and nothing that reads as a grade, rating or certification. Only the path's shape varies.
- It is drawn in `--mark`, at about 1em beside the company name (40 px in the Explorer, 30 px on phones).
- Two companies may get similar seals. That is fine, because the seal identifies nothing.

## Link previews

- `site/img/og.png` (1200×630) is rendered from `scripts/brand/og.html` by `scripts/brand/render_og.sh`. It has one highlight, on a real figure (Apple's fiscal 2026 revenue), with its leader to the 10-K that reports it. Update the figure and its accession together.

## Motion: the provenance moment (B-4)

The one brand interaction lives in `site/prov-card.js` and `site/app/app.css`, which the Explorer and chat share. It happens when a figure (a `.door`) opens its provenance card:

1. **Sweep (0–220 ms).** The highlight sweeps left to right across the figure, as a highlighter does. An ink-on-marker copy of the figure (`::after`, its alt text empty so the figure is read once) is revealed through a growing clip, so every pixel under the marker is ink from the first frame. The frame run checks this at 90 ms.
2. **In the card (80 ms on).** The card's copy of the figure gets the same sweep.
3. **Leader (240–540 ms).** The leader draws from the card's figure, down the card's left gutter, to a dot at the Filing row: the logo's gesture. It is drawn in `--accent-hi`, which is olive on light grounds.

Rules:
- **Hover and keyboard focus** give the same hint, a 2 px accent underline, never yellow text. Enter or Space opens the card exactly as a click does.
- **Reduced motion** (`prefers-reduced-motion`): the highlight and the leader appear at once. There is no sweep and no draw.
- **No layout shift.** Only background-size, stroke-dashoffset and an absolutely placed SVG change, so CLS is 0 at 1440 and 390.
- **After the sweep** the figure sits on the marker colour itself (`background-color`), so contrast checks read it correctly.

## Pre-launch gates (before the site is public)

- [x] **dembrandt competitor check: passed on 24 Nov 2026.** dembrandt 0.41.0 (run by the owner, `provenance-review/brand/dembrandt/RUN.md`) on Koyfin, Fiscal.ai, TIKR, Finviz and AlphaSense found no brand colour within ΔE 10 of the marker (the nearest is TIKR's orange, ΔE 27.5) and no mark that could be confused with the highlight-and-leader. Near-black ink is shared by all of them, as text colour. Details: `provenance-review/brand/dembrandt/COMPARISON.md`. Re-run before launch if the mark or the marker changes.
- [ ] **Trademark clearance** for the name and the mark (owner).
- [ ] **Real tab check** of the favicon on light and dark after any icon change.
- [x] Contrast (WCAG AA) on all four themes at 1440 and 390 (`scripts/ui_checks/check.mjs`).
- [x] Logo and favicon small-size survival: hand-checked (tools blocked).
