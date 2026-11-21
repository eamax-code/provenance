# 24-hour plan, local only (PM, revision of docs/launch-12h.md, 2026-11-22 02:30 IST)

## Owner decisions (2026-11-22, 02:25 IST)
1. **Pricing (§4 of launch-12h.md): approved "fine for now".** G-01 can show the prices on the
   local site. Features that do not exist yet stay hidden (see "G-01 scope" below).
2. **Server: later.** Everything runs locally until the owner is happy with the data and the design.
3. **Everything else after the 24-hour mark:** domain, email, payments, hosted model, news,
   legal. Do not build G-02 (billing), I-01/I-03/I-04 (production host) or I-07 (hosted
   monitoring) in this window.

The 24 hours therefore go into **data depth, linkage, the investor-facing modules and design**,
plus a local production rehearsal. Clock: 2026-11-22 02:30 IST → 2026-11-23 02:30 IST.

## G-01 scope (agreed with the engineering session)
One PLANS source of truth with every flag; enforce only what exists today (rate, quota, export
rows, watches, streams, chat per day, forecasts, `commercial_use` as a label). Free keeps a
100-row CSV export. Watches are webhook-only on every plan until email exists. "Seats" reads
"Keys" (Free 2, Analyst 2, Builder 5, Team 20). Overage and agent credits say "launches with
billing". Commercial display of ESMA/FCA listings data waits for counsel; SEC and GLEIF are clear.

## Phases

| Phase | Hours (IST) | Tickets | Done when |
|---|---|---|---|
| A | 02:30-08:30 | **I-06 local backups** (pg_dump -Fc to `apps/provenance-backups` outside Docker, daily via launchd, keep 3, restore steps in `docs/operations.md`); D-01 mapping + tests; D-05 8-K event types; D-02 dei mapping; I-05 regression test; I-02 doc fix; G-01 | rebuild finished and first dump taken; D-05 and G-01 committed; D-01 tests green |
| B | 08:30-14:30 | D-01 re-normalise (facts-only pass), spot checks AAPL/JPM/XOM/DUK/O, **quality report per metric** (`docs/data-quality-2026-11-22.md`); D-03 ratios; D-04 IFRS; D-06 calendar periods | 30 metrics + ratios live locally; IFRS for TSMC, ASML, SAP; quality ≥ 93% ok per metric or explained |
| C | 14:30-20:30 | **F-02 IPO deal terms** (below); K-01 CIK↔LEI↔ISIN; K-02 officer dates on insider edges; K-03 co-registrants; K-04 ticker/name history; **F-03 insider signals** (connections.md #2) as event types | Anthropic (CIK 2130357) shows price, shares, proceeds, underwriters, exchange, lock-up date; ASML links to its EU listing |
| D | 20:30-02:30 | **Design pass**: company page, Explorer and chat show the new metrics, ratios, events, IPO terms and linkage (desktop + phone, all themes, accessibility + CSP checks); F-01 Sheets function; I-08 load smoke and I-09 smoke script against the production image run locally on real data; backup restore drill | screenshots in the scratchpad, smoke green, `docs/pilot-report.md` updated |

Cut order if behind: F-01, D-06, K-04, K-03, F-03. Never cut I-06, D-01, D-05, G-01, F-02.

## New tickets

**F-02 IPO deal terms (M).** The IPO tracker becomes sellable when it carries the deal, not only
the stage. From the latest S-1/A and the 424B4 already cut into `filing_sections`:
- price range, final price, shares offered (primary and secondary), gross proceeds, underwriting discount
- lead and other underwriters, exchange and ticker, expected first trade date (424B4 date)
- lock-up length and computed expiry date
- quiet-period end (rule-derived: 25 days after the offering)

Rules:
- Parse the cover page and the Underwriting section first; the model is only a fallback.
- Every value carries the verbatim sentence it came from, like officer changes; no value without evidence.
- Rule-derived dates say they are derived.
- Exposed on `GET /v1/ipos`, the MCP tool `companies_going_public`, the company page, and the event types `sec.ipo_priced` and `sec.lockup_expiry`.

**F-03 insider signals (S-M).** Rules on loaded Form 4 data:
- cluster buying: 3 or more insiders buying in the open market within 30 days
- first open-market purchase by an insider in 2 years or more
- 10b5-1 sales vs discretionary sales

Each signal is a feed event and webhook type that links the filings. Call them "activity", never "buy signals".

## PM answers to docs/pm-handover.md §5
1. **Wedge:** both, in two roles. AI builders and fintechs are who *pays* (commercial use at
   $79). The investor modules (IPO pipeline, insider activity, 8-K events) are what *brings people
   in* and what the demo, Show HN and alerts lead with. Build both; sell the first.
2. **Depth order:** line items (D-01) first, because without them nothing else is credible. IPO
   deal terms next, because they are unique and timely (Anthropic). Then 13F. Prices last, with
   the user's own key (GH #29).
3. **IPO tracker:** F-02 above. SPAC tracking and Form D raises come after launch.
4. **Pricing:** approved; see launch-12h.md §4 and the G-01 scope above. Paid-only: webhooks/SSE, forecasts, commercial use and higher limits.
   Never paywalled: citations, `quality_status`, `as_of`.
5. **Owner decisions first:** after the 24 hours: domain + email, then payments, then the model.
6. **Must be true before any public launch:**
   - working backups and a restore drill
   - alerting
   - a "not investment advice; information, not signals" disclaimer on chat, forecasts, insider activity and IPO pages
   - data-licence notes per source on /legal/data-sources
   - an incident runbook in docs/operations.md

## Reporting
The engineering session updates TODO.md as each ticket lands, then commits and pushes. The PM session
checks progress hourly and writes the owner's morning summary to `docs/status-2026-11-22.md`.
