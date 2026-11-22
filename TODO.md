# TODO

Pending work as of 2026-11-15. GitHub Issues (GH #) and older tickets in `.scratch/backlog/issues/`; tracker
conventions in `docs/agents/issue-tracker.md`. Labels: **ready-for-human** needs an owner
decision or account; **ready-for-agent** can be built now; **needs-triage** is an idea.

## 12-hour launch: agent track (started 2026-11-22)
Plan: [docs/launch-12h.md](docs/launch-12h.md) (PM session). Handover: [docs/pm-handover.md](docs/pm-handover.md). Status is updated as each ticket lands.

| Ticket | Item | Status |
| --- | --- | --- |
| I-06 | Backups after the 2026-11-20 local data loss | local part done 2026-11-22: `scripts/backup_db.sh`, daily launchd dump (keep 3), restore steps in docs/operations.md; local DB restored from the 11-05 dump, rebuild from SEC archives running; production object storage waits on the host |
| D-01 | Core statements 5 → 30 metrics (mapping 1.3.0) | mapping, tests, API/MCP/chat wiring and data dictionary done 2026-11-22; industry fallbacks for banks, utilities and REITs; unit check; re-normalisation of all filers runs after the filings rebuild, then spot checks (AAPL, JPM, XOM, DUK, O) |
| D-05 | 8-K item and form events on feed, webhooks, MCP | done 2026-11-22: thirteen filing event types from form and declared 8-K items (`app/services/filing_events.py`); `event_types` on feed, SSE and webhook payloads; `/v1/events?event_type=`; watches limited by type (migration c4f7a2e9b1d6); MCP `recent_events` takes `event_type`; backfill never notifies |
| Live | `GET /v1/public/ipos` and `/v1/public/events` for the home strip | done 2026-11-22: keyless, stored data only, at most 5 rows, cached 60 s, sec.gov filing links, short labels of 24 characters or fewer |
| D-02 | Cover-page facts | done 2026-11-22: `shares_outstanding` and `public_float` from dei (mapping 1.3.0, 32 metrics), filer category and fiscal year end; `cover` on the public company bundle and a cover line on `/profile`, each with its filing. Auditor and PCAOB firm ID come from PCAOB Form AP (connections.md #8), not in SEC company facts |
| D-03 | Derived ratios | done 2026-11-22: margins, ROA, ROE, free cash flow, debt to equity, current ratio, book value per share; at query time with inputs listed, on `/facts`, the screen, MCP and the company page; never stored |
| D-04 | IFRS mapping | done 2026-11-22: `IFRS_MAP` for the 30 metrics (ifrs-full), currency as reported, statements use the reporting currency; about 920 IFRS filers re-read after the main re-normalisation |
| D-06 | Calendar alignment | partly done 2026-11-22: `calendar_period` (CY2024, CY2024Q4, CY2024Q3I, as the SEC frames them) on every fact; a screen filter by it is on the cut list |
| I-05, I-02 | Semantic search regression test; deployment sizing from the rebuilt DB | queued |
| K-01 | CIK, LEI and ISIN | done 2026-11-22: 125 links (33 from the SEC, 11 name and jurisdiction, 81 strict name), match method, confidence and evidence on each; overrides table; overview `identity`, `/profile` line, `sec_cik` on issuers. Listings data reloaded after the loss (6,380 instruments, as before) |
| K-01b | LEI for every SEC filer from the GLEIF golden copy | done 2026-11-22: 3.5M records streamed, 9,605 kept; 6,107 filers linked (5,858 name and jurisdiction, high); US 5,036 of 15,008 (33.6%), foreign 868 of 2,917 (29.8%); 44.2% of active reporters (a 10-K/20-F/40-F in two years), 59.4% of companies with $1B+ revenue |
| K-01c | Normalised LEI matching | done 2026-11-22: SEC state suffixes, The, legal-form spellings (P.L.C., L.P., L.L.C.) and GLEIF other and transliterated names; match only where names and jurisdiction agree and one candidate (high when the jurisdiction matches exactly); filers whose SEC record has no state of incorporation (GM, Oracle, HCA, Broadcom) match by a unique exact name at medium, as agreed for K-01b. Two samples of 30 $1B+ links hand-checked: 59 right, 1 doubtful (ADT). Coverage: 79.2% of active $1B+ companies (1,436 of 1,813), 72.5% of all $1B+, 50.7% of active reporters; target 85% not reached |
| K-01c+ | LEI re-check | done 2026-11-22: GLEIF previous legal names kept (never matched); filers with no SEC place of incorporation also match a unique normalised, translated or transliterated name at medium (TSMC, Mitsui, Takeda), never via a previous legal name or an /OLD registrant (first sample 3 doubtful in 30, all previous names; after tightening 30 of 30 right); Linde high after the plc fix; Pemex cited override. Closed at 81.8% of active $1B+ companies (1,510 of 1,845) |
| K-01d | LEI backlog | done 2026-11-22 (c183818): rule (a) `gleif_name_us_state_differs` at medium, only with the business city in GLEIF's address and an LEI no other filer holds (735 links; hand-check 30 of 30 right). Coverage of active USD $1B+ companies 81.2% -> 84.2% (1,598 of 1,898), active reporters 51.7% -> 53.8%. Chevron: no Chevron filing carries its own LEI (the full-text hits are trustees' Form T-1s) and the golden copy has no Chevron Corporation entity, so it stays unmatched. Registration-authority IDs: GLEIF's are state or national file numbers that the SEC data does not carry, so no local match is possible |
| E-1 | 13F institutional holders | code done 2026-11-22 (afd5294): data sets Q3 2025 to Q2 2026 on disk, CUSIP map from Schedule 13D/G (cached), API, MCP, overview block; load after the pass; E-1b (Q3 2026 per filing) approved after the load |
| E-2 | First reported from 8-K 2.02 releases | code done 2026-11-22 (5621f5a): dry run 102 of 122 matched, none wrong; batch 1 (top 500, 4 releases) after the pass, batch 2 overnight |
| E-3 | Auditor | code done 2026-11-22 (d79c222): from the Notes data sets (12 months on disk); PCAOB Form AP (partners) needs the owner to download it in a browser; load after the pass |
| E-4 | Segments, first pass | code done 2026-11-22 (54985d6): business, geographic and product from the Notes data sets; load after the pass |
| E-4b | Segment member labels | queued: the filing's own labels from its label linkbase (_lab.xml) through the shared SEC limiter, top 500 by revenue first; until then label_source "member_name" |
| K-06 | Display names and addresses | done 2026-11-22 (1ad04f5, ea7f8fc, a29b6ea): `registrant_name` from dei:EntityRegistrantName as filed (latest report, Notes data sets); `display_name` uses it when written with real casing, else the conformed name without its EDGAR suffix (Toyota Motor Corp, SAP SE); `legal_name_as_filed` with its filing on the company, profile and overview; foreign addresses take the country from EDGAR's state/country code, never a default United States |
| K-05 | Successor registrants (P1) | code done 2026-11-22 (49888f9): 23 pairs in 10 years (XOM, Linde, Baker Hughes...); store and hand-check after the pass |
| K-03 | Co-registrants | done 2026-11-22: graph layer `co_registrants` from 10-K/10-Q/8-K filed under one accession by several registrants in 3 years (Duke Energy and its six utilities); filings indexed by accession |
| P-01 | Public statistics from a stored snapshot | done 2026-11-22 (stats): a request reads one stored row, never the aggregates (tested); refreshed every 45 s by the web process (`STATS_REFRESH_SECONDS`) and by the poller; a stale snapshot is served with its generated_at. Coverage follows the same pattern |
| K-04 | Ticker and name history | done 2026-11-22: a ticker a company leaves is kept as a former ticker and search finds the company by it (`match_type=former_ticker`); former names were already searchable; overview `former_tickers`. The SEC publishes only current tickers, so ticker history starts accumulating now |
| G-01 | Pricing in code, one source of truth (owner approved prices 2026-11-22) | done 2026-11-22: `app/core/plans.py` (Free, Analyst $19, Builder $79, Team $249, Enterprise from $1,500); enforced: rate, quota, export rows, watches, streams, chat per day, forecasts (Analyst+), keys per account; `commercial_use` as a label; overage and credits hidden until G-02; `/v1/public/plans`, `site/plans.json` and the home JSON-LD from `scripts/sync_plans.py` (provenance-ui runs it with its home commit) |
| T-01 | Type watches across companies (Builder+), universe filter, hourly batch for high-volume types | done 2026-11-22: `POST/GET/DELETE /v1/type-watches`; universe by SIC prefix, exchange, filer category or up to 500 CIKs; rare types one by one, results/agreements/votes without a universe as one `sec.filing.batch` webhook an hour; counts as one watch; same signing; backfill never notifies (migration d9e2b6f4a8c3) |
| U-01, U-02 | Public as_of on the company overview; peers | done 2026-11-22: `/v1/public/companies/{cik}/overview?as_of=` (statements, figures, filings, leadership, events point in time; summary, peers, risk, listings current and labelled); `statements` (32 metrics by fiscal year, ratios with inputs), `cover`, `events`; peers by 4-digit SIC (3 when fewer than 4), annual report in 2 years, closest revenue, at most 6. Example: docs/api-examples/public-overview.json |
| K-02, U-03 | Officer dates on insider edges; leadership by person | done 2026-11-22: an 8-K 5.02 departure or retirement ends an insider's role at once (or on its later effective date: `leaving_on`), on the graph and the overview; `leadership.people` grouped by person with events newest first; `current_leadership` CEO, CFO and chair from the latest 8-K appointment, else the Form 4 title; never a departed person; vice chairs and committee chairs are not the chair |
| F-02 | IPO deal terms | done 2026-11-22: price range, final price, shares (new and sold), proceeds, discount, exchange and ticker, underwriters and leads, lock-up (and expiry, derived), quiet period end (derived), closing date; every value with its sentence; Anthropic: range $70-78, priced $83, 980M shares, $81.3B, Goldman Sachs and Morgan Stanley lead, 180/365-day lock-up. `sec.ipo_priced` done (first 424B4 after registration, stored as a filing tag at ingestion); `sec.lockup_expiry` done (dated event emitted on the day by the tracker, feed kind `calendar`, type watches) |
| IPO pages | Keyless `/v1/public/ipos/pipeline` (by stage, terms values, counts, `lockup_within_days`) and `/v1/public/ipos/{cik}` (terms with evidence); `/v1/ipos?lockup_expiry_within_days=` | done 2026-11-22 |
| S-01 | Summary text formatting at the source | done 2026-11-22: dates as "26 Sep 2026", forms as plain names from one map (`app/services/form_names.py`: "an insider trade report (Form 4)"), leadership sentence says what happened; `form_label` on overview filings and events |
| F-03 | Insider activity events | done 2026-11-22: cluster buying, first buy in 2+ years, large sale outside a 10b5-1 plan; feed kind `insider`, type watches, MCP, `/v1/public/insider-activity`, company overview; backfill never notifies |
| C-01 | Chat: IPO terms intent | done 2026-11-22: "What were Anthropic's IPO terms?" / "Who underwrote X?" answered from the stored terms without a model, every sentence cited, the card carries each sentence; S-01 in chat: readable dates, plain form names, counts in words, unread 5.02 filings last |
| P0 | No detection timestamps in responses | done 2026-11-22: `detected_at` removed from listing events (keyed, public, feed, webhooks); `detected_since` replaced by `until` on the event's own date; a test fails if any response model or the OpenAPI schema carries `*detected_at*`, `first_detected*` or `source_updated*` |
| A-01 | Alerts panel API | done 2026-11-22: `GET /v1/type-watches/{id}/deliveries`; `POST /v1/type-watches/{id}/test` and `/v1/listing-watches/{id}/test` (signed sec.test); `PATCH` pause and resume on all three watch kinds (paused: nothing sent or queued, still counted); keyless `GET /v1/event-types` from the one registry (label, short label, immediate or hourly batch, min plan) |
| I-09, F-01 | Production smoke script, Sheets function | queued |
| E-4b+ | Segment labels for older annual reports (low priority, background) | ready-for-agent: `python scripts/load_segment_labels.py` without `--latest` labels the reports before each company's latest (the E-4c reload holds 24,953 reports filed 2021-01 to 2026-10; the latest ones are labelled). About 40k SEC requests, about 1.5 h at 8 req/s through the shared limiter. Run only when no other SEC job is going and never during a mapping pass; resumable, since filed documents are cached and a rerun sends no request for a report already read. Until then older reports show labels made from member names (`label_source` member_name) |
| E-4d+ | Segments: a side mixing solution lines with revenue types (needs-triage; do not build yet) | E-4d keeps the finer of two whole breakdowns when both add up within 0.1%; ACI Worldwide FY2025 passed that while each side mixed solution lines (Bill Payments, Real-Time Payments) with revenue types (License, Maintenance). Held by a reviewed override in `app/data/segment_overrides.csv` (kept unreconciled, members as tagged). A general rule (for example, members classed as solution vs revenue type from their labels) needs its own dry run and hand-check |
| M-150 | Mapping 1.5.0: the income-statement revenue line as the tie-breaker (PM approved 2026-11-22; first engineering item after the 24-hour window, after the 1.4.1 pass is clean) | ready-for-agent. Build: a per-filing table of revenue candidate tags on the income statement, with labels, from the Notes data sets' pre.tsv (stmt=IS, not parenthetical), reloaded as new files arrive; used only inside the conflict/precedence step: when exactly one candidate is on the income statement (under any label) and its label reads as a total, it is preferred. Data dictionary rule; own full pass. Dry run (v3): of 5,946 in-filing revenue conflicts, 2,441 in Notes coverage (filings 2021-01 on); 1,621 settled at 202 companies (773 keep the total, 848 take the other tag); 864 stay open; 637 ok values change at 90 companies (Republic Services 2022 $13,511M, not a gross $15,645M). Gate: a 30-company hand-check on the built code, at most 1 wrong, Williams FY2025 named ($11.95B); a before/after line in the quality report for the changed ok values; the changelog lists them plainly as a restatement of our own output; as_of answers carry the version  Also in 1.5.0 (PM ruled 2026-11-22), with its own changelog line and its own before/after in the quality report: IFRS bank revenue. ifrs-full RevenueAndOperatingIncome, and GrossProfit for banks and financial holding companies (SIC 6000-6299) only, each only where the filing's own income statement shows that tag under a total-income label ("Total operating income", "Total revenues", "Total income", "Gross income", "Net operating income/profit before ..."); the unguarded fallback was wrong for BBVA (EUR 0.32B, an unrelated line) and Santander Brasil. Dry run: 39 bank-years at 10 banks (HSBC Holdings, HSBC Bank plc, UBS Group, UBS AG, Santander, BBVA FY2020, BBVA Argentina, Galicia, Santander Chile, SEK); 64 candidate years refused; hand-check 20 of 20 against the filed income statements (HSBC FY2025 $68,274M total operating income, UBS Group $49,573M total revenues, Santander EUR 58,670M total income, BBVA FY2020 EUR 20,166M gross income). Uses the same per-filing income-statement label table as the tie-breaker. The changelog and data dictionary state the definition plainly: "bank revenue = the total income line on the income statement, after interest expense, as the bank labels it" (HSBC, UBS and Santander report on that basis), so it is not compared unawares with US banks' gross revenue |
| Owner | O-01 to O-09 (host, domain, email, merchant of record, model, news, legal, pricing) | waiting on you; G-02, I-01, I-03 wait on them |

## Pilot launch: working list (started 2026-11-15)
Status 2026-11-15 06:20 IST: everything an agent can build is done. What is left needs you; see "Decisions that block launch" in [docs/launch-plan.md](docs/launch-plan.md).
Also built beyond the list: `LLM_PROVIDER=openai` (GH #13 is now a settings choice), `NEWS_PROVIDER=gdelt` for production (GH #14), `scripts/pilot_metrics.py`, `examples/point_in_time.py`, acceptance-to-availability on the status page, and the measured local refresh in docs/pilot-report.md.

Goal: a pilot that strangers can use without us in the room. That means every page in one layout, docs a
developer can follow alone, sign-up without an operator, a security pass, an agent-ready MCP server,
draft legal pages, and fresh SEC data. Items marked "you" need an owner decision; everything else
is being built now.

| # | Item | Ticket | Status |
| --- | --- | --- | --- |
| P1 | SEC data refreshed from the latest nightly archives (new filings and new companies), marts rebuilt | ops | done 2026-11-15: 21,586 companies, +120,057 filings, +50,168 facts, 0 failures |
| P2 | Every page in the shared layout: developer docs, API reference, changelog, 404 and error pages | GH #11, #20, #21 | done 2026-11-15 |
| P3 | Developer docs: quickstart in curl/Python/JS, guides, error codes, limits, changelog, versioning policy | GH #20 | done; client builds and passes `twine check`, publish workflow on `client-v*` tags; PyPI trusted publisher: you |
| P4 | SEO: sitemap.xml, robots.txt, canonical links, Open Graph image and tags on every page | GH #21 | done (set `site/shell/site.json` origin and `PUBLIC_BASE_URL` once the domain is chosen) |
| P5 | Accessibility: skip link, landmarks, focus order, labels, automated check on every page | GH #21 | done: 14 pages x 2 widths, all four themes, no findings |
| P6 | Performance: cache headers for static files, home page weight budget | GH #21 | done: gzip, cache headers, photos 970 KB to 290 KB, 40 KB home budget test |
| P7 | Security: headers and CSP, CORS, pip-audit in CI, /poc/ off in production, chat abuse limits, prompt-injection review | GH #18 | done: [docs/security.md](docs/security.md); new secrets before launch are yours |
| P8 | MCP server over the API: tools for search, overview, figures with as_of, filings, events, listings | GH #22 | done: `POST /mcp`, 8 tools, install lines on /developers/#mcp |
| P9 | Accounts: sign-up and sign-in by email link, profile with keys, usage and theme, claim an issued key | GH #15 | done: /account/; sending real email waits on 06 (until then sign-in answers 503 and points to the key request) |
| P10 | Draft Terms, Privacy, Acceptable use and Data sources pages, marked draft until legal review | GH #17 | drafts done at /legal/; bracketed owner notes (liability cap, law, providers) and final wording: you, after 05 |
| P11 | Pilot launch plan: who it is for, the offer, success measures, launch-day checklist, outreach copy | 03 | done: [docs/launch-plan.md](docs/launch-plan.md); interviews and outreach: you |
| P12 | Deployment check without a host: image builds, readiness checks, env example, runbook current | GH #19 | done: image built and run in production mode; `.dockerignore`; settings table in docs/deployment.md (host: you, 02) |
| P13 | Tests: unit tests for all new code, full suite on SQLite and Postgres, every page in a browser at desktop and phone width | all | done 2026-11-15: 477 SQLite, 481 PostgreSQL, 477 with the clock two years ahead; migrations up/down; 20 pages pass accessibility and CSP checks; GitHub CI green |
| P14 | Connections graph in the Explorer: insiders (Forms 3/4/5), board interlocks, 5% holders (13D/G), subsidiaries (exhibit 21); API, MCP tools, daily upkeep; deep dive on what to add | you, 2026-11-18 | done: ADR 0011, [docs/connections.md](docs/connections.md); 20 quarters of insider data loaded (2.7M rows); exhibits and 13D/G read for the 12 showcase companies |
| P15 | Anthropic went public (424B4, 2026-11-19) and the local copy stopped at 11-12: read EDGAR every hour, refresh covered companies, add companies going public, show IPO stages | you, 2026-11-19 | done: ADR 0012, `GET /v1/ipos`, MCP `companies_going_public`; poller runs it hourly, `scripts/track_filings.py` for catch-up; local hourly run via launchd |

## Release 1.0
Checklist: [GH #31](https://github.com/eamax-code/provenance/issues/31). Milestone "Release 1.0" on GitHub.

### Needs you
| # | Item | Why it is blocked |
| --- | --- | --- |
| 02 | [Choose a host and deploy the pilot](.scratch/backlog/issues/02-deploy-pilot.md) | Account, domain, payment |
| 05 | [Legal review of data rights; final name](.scratch/backlog/issues/05-legal-and-brand.md) | Before selling |
| 06 | [Email provider](.scratch/backlog/issues/06-email-provider.md) | Account and sender domain; sign-up needs it |
| GH #13 | [Production language model: where chat, extraction and forecasts run](https://github.com/eamax-code/provenance/issues/13) | Hosted API or GPU host, and a budget |
| GH #14 | [Forecasts: replace Google News RSS before selling](https://github.com/eamax-code/provenance/issues/14) | GDELT, a licensed API, or filings only |
| GH #16 | [Billing for Builder and Team](https://github.com/eamax-code/provenance/issues/16) | Payment provider; prices |
| GH #17 | [Terms, privacy, acceptable use, data sources pages](https://github.com/eamax-code/provenance/issues/17) | Drafts can start; final after 05 |
| GH #23 | [Credits, levels and quests in chat and the playground](https://github.com/eamax-code/provenance/issues/23) | Reward amounts; needs #15 |
| 20 | [Officer changes: confirm the "evidence, not signals" framing (and Indian counsel on SEBI rules) before any score](.scratch/backlog/issues/20-officer-change-analysis.md) | Your decision; the feed, context and base rates are built |
| 03 | [Live-week pilot report and outreach](.scratch/backlog/issues/03-pilot-report-and-outreach.md) | Needs a deployment and interviews |

### Ready for agent
| # | Item |
| --- | --- |
| GH #11 | [One layout and the dark theme on every page](https://github.com/eamax-code/provenance/issues/11) (done, closed 2026-11-12) |
| GH #12 | [Theme choice in the profile for chat and the Explorer](https://github.com/eamax-code/provenance/issues/12) (done, closed 2026-11-12) |
| GH #10 | [Company page: a figure's mini trend opens a large chart with insights](https://github.com/eamax-code/provenance/issues/10) (done, closed 2026-11-12) |
| GH #15 | [Accounts: self-serve sign-up, sign-in and a profile](https://github.com/eamax-code/provenance/issues/15) (email delivery waits on 06) |
| GH #18 | [Security review before launch](https://github.com/eamax-code/provenance/issues/18) |
| GH #19 | [Production data and monitoring](https://github.com/eamax-code/provenance/issues/19) (after 02) |
| GH #20 | [Developer docs: quickstart, guides, changelog, versioning, PyPI](https://github.com/eamax-code/provenance/issues/20) |
| GH #21 | [Launch polish: SEO, accessibility, performance, 404](https://github.com/eamax-code/provenance/issues/21) |
| GH #22 | [MCP server so AI agents can query Provenance and cite it](https://github.com/eamax-code/provenance/issues/22) |

## After release
Milestone "After release": the gaps with Bloomberg and FactSet that free, redistributable sources can close.

| # | Item | Status |
| --- | --- | --- |
| GH #24 | [Ownership: insider trades, 13F, 13D/G, fund holdings](https://github.com/eamax-code/provenance/issues/24) | in progress: insiders, transactions, 13D/G and the connections graph done 2026-11-18 (ADR 0011); 13F and N-PORT next, see [docs/connections.md](docs/connections.md) |
| GH #25 | [About 100 standardised line items and segments](https://github.com/eamax-code/provenance/issues/25) | ready-for-agent |
| GH #26 | [Company guidance from earnings releases](https://github.com/eamax-code/provenance/issues/26) | ready-for-agent |
| GH #27 | [Company financials outside the US](https://github.com/eamax-code/provenance/issues/27) | needs you: licence per source |
| GH #28 | [Economic data: rates, inflation, output](https://github.com/eamax-code/provenance/issues/28) | ready-for-agent |
| GH #29 | [Market prices: licensed end-of-day or the user's key](https://github.com/eamax-code/provenance/issues/29) | needs you: vendor and budget |
| GH #30 | [Excel and Google Sheets add-in](https://github.com/eamax-code/provenance/issues/30) | ready-for-agent |
| 19 | [Bulk Parquet snapshots](.scratch/backlog/issues/19-parquet-snapshots.md) | needs you: bounded-export rule, 05 |
| 04 | [TMX / CSE permissions for Canadian feeds](.scratch/backlog/issues/04-canadian-exchange-permissions.md) | needs you: non-commercial terms |

## Future scope
Sources and sub-products flagged for later, each with a description: [docs/future-scope.md](docs/future-scope.md).
So far: EIA-860 (US power plants and generators).

## Done
GH #9 the company page is Snapshot, with Report and Dossier as layouts a reader picks (2026-11-10), 21 the ChatGPT design with clay.com-style motion is the main page (2026-11-06), 01 (SEC contact address in local config; 20,540 companies loaded from the bulk archives), 11 usage series, SEC responses by endpoint, detection-to-processing latency, 07-10 listings: GLEIF identity in batches, non-share exclusion and primary-listing flag,
listing watches, Listings view in the Explorer; 12 shared rate limits, 20 officer changes on the feed within minutes with point-in-time
context and measured base rates, daily retention, webhook alerts, 15 test hygiene
(no warnings, `--clock`), 16
point-in-time facts, 17 event feed, 18 Python client. GitHub Issues #1 to #8 are closed (search,
marts, profiles and /v1/search, chat flow, redesigns).

## Ideas
| # | Item |
| --- | --- |
| 13 | [Canadian reporting issuers from OSC open data](.scratch/backlog/issues/13-canada-reporting-issuers.md) |
| 14 | [Company event feed (information, not signals)](.scratch/backlog/issues/14-event-feed-idea.md) |

Outside this repo: the DistrictLens cyclone module spec is at
`apps/research/districtlens-cyclone-impact-spec.md`; it needs a repo location before tickets,
and GDACS (JRC) and JTWC reuse confirmations before a paid tier.
