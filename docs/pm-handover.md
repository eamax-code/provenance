# Provenance: handover for the product manager (2026-11-22)

Written by the engineering session that has built Provenance since late October 2026. The repo is
`apps/provenance`, GitHub `eamax-code/provenance` (125 commits on `main`). Read this first, then
`docs/launch-plan.md` (the bet, buyers, offer, measures) and `TODO.md` (live status).

## 1. What Provenance is

A public-company data API built only on official, redistributable sources (SEC EDGAR first;
EU, UK and Canadian listing registers second). **The bet:** AI products and small fintech teams
need company facts they can cite. Every figure carries its filing (accession number, XBRL tag,
mapping version), can be asked "as of" a past date with no look-ahead, and reaches an agent
through one MCP line.

Buyers, in order (launch plan): (1) AI application builders who must cite figures; (2) small
fintech and data teams that need point-in-time fundamentals, an event feed and webhooks without a
terminal licence; (3) analysts and researchers via the chat and Explorer, who convert into 1 and 2.
**Not for:** traders. We have no prices, estimates or intraday data, and say so on every page.

Pricing on the site: Free (60 req/min, 10k/month, MCP and Python client), Builder $49/month,
Team $199/month, Enterprise after legal review. Pilot offer: first ten design partners get Builder
free for 60 days in exchange for fortnightly calls and quotes.

Status: **built and tested locally, not deployed, no users yet, zero interviews done.** Every
blocker to launch is an owner decision (section 4).

## 2. What is built

### Data
| Area | What we have | Source |
|---|---|---|
| Company identity | ~21.6k SEC filers: CIK, tickers, exchanges, SIC, state, former names ("facebook" finds Meta) | SEC submissions, ticker file |
| Filings | Every filing per company with document links, 8-K item codes (5.02 etc.) | EDGAR |
| Financial facts | **Five normalised metrics**: revenue, operating income, net income, total assets, operating cash flow; annual and derived quarters; `quality_status` per value (95.4% ok, 4.0% ambiguous mapping, 0.6% partial); `as_of` point-in-time | XBRL companyfacts |
| Marts | Company-year tables, growth, screens across all companies by year or quarter | derived (ADR 0009) |
| Filing text search | Keyword search of stored filing sections; semantic search with the caller's own embedding key | filings (ADR 0008) |
| Officer changes | 8-K item 5.02 extracted with verbatim evidence, point-in-time context and measured base rates; framed as "evidence, not signals" | 8-K text |
| Connections | Insiders (Forms 3/4/5) with roles, holdings and 12-month buys/sells; board interlocks; 5% holders (13D/G, structured since Dec 2024); subsidiaries (exhibit 21) with year-on-year changes | SEC insider data sets, filings (ADR 0011) |
| IPOs (new, 2026-11-19) | Companies going public by stage: confidential draft, filed, amended, effective, listing (8-A12B), priced (424B4), withdrawn; each milestone links its filing; SPACs flagged by SIC 6770 | EDGAR (ADR 0012) |
| International listings | 38 venues in the EU, UK and Canada: instruments (ISIN), issuers (LEI), new listings, delistings, suspensions, name changes | ESMA FIRDS, FCA, GLEIF, TMX/CSE |

### Freshness
- **Hourly filings tracker (new, 2026-11-19):** reads EDGAR full-text search (IPO and periodic
  forms, today and yesterday), the latest-filings feed (all forms, often slow) and the daily index
  (complete record, next morning). Companies we cover are refreshed when they file; companies
  filing an S-1/F-1, 424B4, 8-A or a first 10-K/10-Q are added. Funds and ETF trusts are skipped.
  Runs inside the poller in production; a launchd job on the owner's Mac locally.
- Event feed (ordered, resumable, SSE) and signed webhooks for new filings and listing events.
  First ingestion of a company is a backfill and does not notify (ADR 0004).
- Status page publishes SEC-acceptance-to-API latency (median and p95), no promise.

### Delivery
- REST API (`/v1/...`, OpenAPI at `/docs`, own reference at `/developers/`), about 55 endpoints.
- **MCP server** at `/mcp`: eleven read-only tools (search, overview, facts with `as_of`, screen,
  filings, events, listings, connections, insider transactions, companies going public, profile).
  Checked with the official MCP Python SDK.
- Python client (ready for PyPI; publishing needs the owner's PyPI account), `llms.txt`.
- Bounded CSV/JSON exports with provenance columns.
- **Chat** (`/chat/`): answers figures, trends, rankings and tables from data without a model;
  a model (local Qwen3 4B now, any OpenAI-compatible API by setting) writes summaries. Answers that
  cite no filing are withheld.
- **Explorer** (`/app/`): search, filings, facts chart with provenance, freshness, Connections
  graph, Listings, developer console.
- Public site: home with pricing, company directory and pages, status, playground (demo key,
  showcase companies only, never triggers SEC fetches), developer docs, changelog, draft legal
  pages, accounts (sign-in by email link; sending email waits on a provider).

### Engineering quality
- ~530 tests, green on SQLite and PostgreSQL, with the clock moved two years ahead; migrations
  up and down; accessibility and CSP checks on every page at two widths; GitHub CI green.
- Security pass done (headers, CSP, CORS off, pip-audit, chat caps, prompt-injection rules).
- 12 ADRs record the design decisions (`docs/adr/`).

## 3. Incident today (2026-11-22): local database lost

Docker Desktop's disk image disappeared between 2026-11-19 23:33Z and 2026-11-20 18:54Z (cause
unknown; logs from before the reset are gone). The local Postgres container and all its data
went with it. Nothing in the repo is affected, and production does not exist yet.

- Restored from the only backup, `apps/provenance-backups/provenance-2026-11-05.dump`.
- Lost since 5 Nov and to be rebuilt: the 15 Nov nightly refresh (+120k filings, +50k facts),
  20 quarters of insider data (2.7M rows), exhibit 21 and 13D/G reads for the showcase companies,
  officer changes since 5 Nov, the IPO tracker's feed and its new companies. All of it comes from
  public SEC sources, so it is a re-run, not a loss of anything unique. The hourly tracker skipped
  every run since 20 Nov because the database was down.
- **Product lesson:** a scheduled backup (nightly `pg_dump` with rotation) and an alert when the
  hourly job skips are missing. These are cheap and should come before any pilot.

## 4. What is left

### Owner decisions that block a public pilot (in unblock order)
1. **Host and domain (02):** Fly or Render, about ₹4,000/month at pilot scale; deploy files ready.
2. **Email provider (06):** sign-in links depend on it.
3. **Where the model runs (GH #13):** hosted OpenAI-compatible API (settings change), GPU host, or
   no model at launch (data answers still work).
4. **News for forecasts (GH #14):** GDELT (set), a licensed feed, or filings only.
5. **Legal review and final name (05):** before paid plans; drafts at `/legal/`.
6. **Billing (GH #16):** can wait for the first partner who wants to pay.
7. Also: PyPI publisher, production secrets, the officer-change framing (20), credits and quests
   in chat (GH #23), Canadian exchange permissions (04), bulk Parquet rule (19).

### Roadmap the engineering side can build now (GH milestone "After release")
| # | Item | Notes |
|---|---|---|
| GH #24 | Ownership: 13F institutional holders, N-PORT fund holdings | insiders and 13D/G done |
| GH #25 | ~100 standardised line items and segments | today only five metrics, the biggest depth gap |
| GH #26 | Company guidance quoted from earnings releases (8-K ex. 99) | needs the model for extraction |
| GH #28 | Economic data: rates, inflation, output | FRED/BLS/BEA, public |
| GH #30 | Excel and Google Sheets add-in | analyst distribution |
| connections.md | 14 ranked graph additions (leadership dates on edges, insider cluster-buy alerts, person view, co-registrants, GLEIF parents, M&A counterparties, auditors, underwriters...) | several are S effort |
| GH #27, #29 | Non-US financials, market prices | need licences and budget |

### Gaps an investor-minded reader will spot (my honest list)
- **Depth:** five metrics against hundreds at FMP, EODHD, Intrinio, sec-api.io or Fiscal.ai. No
  segments, no per-share data, no balance-sheet detail beyond total assets, no ratios.
- **No prices,** so no market cap, valuation multiples or returns. A real gap for investors; a
  deliberate scope choice for licensing.
- **IPO data stops at the filing level:** no price range, shares offered, proceeds, underwriters,
  first trade date or exchange. "Priced" (424B4) is not "trading".
- **No estimates or consensus,** no transcripts.
- **Coverage of private-market signals** (Form D raises, Reg A) is not read, though public.
- **Freshness is measured, not promised;** the latest-filings feed is slow, so intraday reads lean
  on full-text search; Form 4s are complete only the next morning via the daily index.
- **Untested demand:** no interviews, no trials, no users.

## 5. Questions I would like the PM's view on
1. Is "citable facts for AI builders" the right wedge, or is an investor-facing use (IPO pipeline,
   insider activity, officer changes) a stronger first product?
2. Which depth gap matters most for the first ten design partners: line items (GH #25), ownership
   (13F), IPO deal terms, or prices?
3. What would make the IPO tracker sellable: deal terms from the S-1/424B4, lock-up expiry dates,
   first trade and exchange, underwriters, quiet-period end, SPAC merger tracking?
4. Pricing: are $49 and $199 right for the buyers above? What should be paid-only (webhooks,
   `as_of`, exports, MCP volume)?
5. Which owner decisions should be made first to get a pilot in front of people this month?
6. What must be true before launch beyond the list in section 4 (backups and monitoring, data
   licences, disclaimers on investment use)?
