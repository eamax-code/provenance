# 12-hour launch plan (PM review, 2026-11-22)

Written by the PM session (`provenance-pm`) after a review of the repo at b10d330, `TODO.md`,
`docs/launch-plan.md`, `docs/connections.md`, `app/core/config.py` and the open GitHub issues.
Goal: **Provenance is live on a real domain, takes money, and is worth paying for, 12 hours from
start.** Personal project: no BrightQuery resources, accounts, data or credentials anywhere.

Ticket IDs: **O** = owner decision, **I** = infrastructure, **D** = data, **K** = linkage,
**F** = feature, **G** = go-to-market and pricing. Effort: S ≤ 2 h, M ≤ 4 h. Every agent ticket
ships with tests (SQLite + Postgres) and a changelog line.

---

## 1. Where the product stands

Strong: provenance on every figure, `as_of` with no look-ahead, event feed + SSE + signed
webhooks, MCP (11 tools), Python client, connections graph (insiders, 13D/G, exhibit 21),
IPO stages from the hourly filings tracker, EU/UK listings, chat with grounding, accounts,
security pass, docs, legal drafts. That is more than most paid filings APIs ship.

### The gaps a buyer will hit in the first 10 minutes

| # | Gap | Why it matters | Fix in 12 h? |
|---|---|---|---|
| 1 | **Only 5 normalised metrics** (`CONCEPT_MAP`: revenue, operating income, net income, total assets, operating cash flow) | An analyst's first query is EPS, gross margin, debt, cash, shares or free cash flow. Five metrics reads as a demo, not a data product. FMP/EODHD/sec-api expose full statements. | Yes, D-01 to D-03 |
| 2 | **No IFRS** (`TAXONOMIES = ("us-gaap",)`) | Foreign private issuers filing 20-F in IFRS (TSMC, ASML, SAP, Novartis, Shell, Toyota-style ADRs) have no figures, and those are exactly the companies that link to the EU/UK listings. | Yes, D-04 |
| 3 | **8-K items stored but not sold** | Restatements (4.02), auditor changes (4.01), bankruptcy (1.03), M&A (1.01/2.01), change of control (5.01) are the alerts compliance and fintech teams pay for. Only 5.02 reaches the feed. | Yes, D-05 |
| 4 | **US filers not linked to their listings** | The EU/UK listings product and the SEC product are two islands. CIK↔LEI↔ISIN is the bridge. | Partly, K-01 |
| 5 | **Production sizing is wrong in docs** | `docs/deployment.md` budgets a 1 GB Postgres; the local DB is 8 GB+ (8.7M filings, 5.6M facts, 2.7M insider rows, chunk embeddings). | Yes, I-01 |
| 6 | **Semantic search needs Ollama at query time** (`semantic_search.py`) | `/v1/search?mode=semantic` breaks on a host without an embedding model. | Yes, I-05 |
| 7 | **Pricing is volume-only and $49 sits in no-man's land** | See §4. The value buyers pay for elsewhere is the *commercial-use right*, and we can grant it cheaply because the data is public domain. | Yes, G-01/G-02 |
| 8 | **No way to take money** (GH #16) | No revenue on day one. | Yes, G-02 |
| 9 | No prices, so no valuation multiples (P/E, EV/EBITDA) | Real gap vs terminals, but by design. Say it plainly; GH #29 later. | No |

---

## 2. Owner decisions, hour 0 (blocks everything; ~45 min)

| ID | Decision | Recommendation |
|---|---|---|
| O-01 | Host | **One VM with Docker Compose (deployment Option C)**: 4 vCPU / 8 GB RAM / 160 GB disk, e.g. Hetzner CPX31-class (about €15/month, check current price). Fly/Render managed Postgres at 20 GB+ costs more and restoring 8 GB+ is slower. Cloudflare (free) in front for TLS edge, caching of static pages, and DDoS. |
| O-02 | Domain | Buy now; DNS to Cloudflare. Needed for email (SPF/DKIM) and OAuth-free sign-in links. |
| O-03 | Email (06) | Resend or Postmark over SMTP (free tiers cover the pilot). Verify the domain. |
| O-04 | Payments (GH #16) | **A merchant of record** (Paddle, Lemon Squeezy or Dodo Payments): handles global VAT/GST and pays out to an Indian individual. Stripe direct is harder to open for an individual in India and leaves tax with you. Check each one's current onboarding before choosing. |
| O-05 | Model (GH #13) | `LLM_PROVIDER=openai` against a hosted provider that serves the same Qwen3 models (prompt parity), with a hard monthly spend cap (start at $30). Demo key: data-only answers, no model. |
| O-06 | News (GH #14) | `NEWS_ENABLED=false` at launch. Forecasts from filings only. GDELT later if users ask. |
| O-07 | Legal (05/GH #17) | Launch as "pilot" with the drafts finalised for commercial-use definition and attribution (G-03). No person view, no bulk export until counsel. **Counsel confirms the ESMA/FCA FIRDS display terms before we sell commercial display of listings data.** SEC data and GLEIF (CC0) are clear; if counsel is slow, the Builder commercial right covers SEC-derived data first and listings carry their source attribution. |
| O-08 | Pricing | Approve §4 (or edit it), because code, site and checkout all read from it. |
| O-09 | Contact | SEC User-Agent uses the personal address already in `local/local.env`; never the work address. |

---

## 3. Tickets and schedule

**The 12-hour clock starts when the companyfacts download for the rebuild is done** (2026-11-22). Two tracks run in parallel: **owner** (accounts, DNS, keys) and **agent** (code). Agent work
starts at hour 0 on branches that do not need the owner.

### Hours 0-4: data depth (agent) | accounts and VM (owner)

| ID | Ticket | Acceptance | Effort |
|---|---|---|---|
| **D-01** | **Core statements: 5 → 30 metrics** (mapping 1.3.0). Income: revenue, cost_of_revenue, gross_profit, r_and_d, sga, operating_income, interest_expense, income_tax, net_income, eps_basic, eps_diluted, shares_basic_weighted, shares_diluted_weighted, d_and_a. Balance: cash_and_equivalents, current_assets, total_assets, current_liabilities, total_liabilities, long_term_debt, debt_current, stockholders_equity, retained_earnings. Cash flow: operating_cash_flow, capex, dividends_paid, share_repurchases, sbc. Units: USD, USD/shares, shares. Tag precedence per concept, per-filing conflict rule unchanged. | Re-normalise from the local `companyfacts.zip`; `quality_status=ok` ≥ 93% across new metrics; Apple, JPMorgan, Exxon, a utility and a REIT spot-checked against their 10-K; banks get revenue from `Revenues` / net interest income rules, documented in the data dictionary | M |
| **D-02** | **Cover-page facts (dei)**: shares outstanding, public float, filer category (large accelerated, accelerated, non-accelerated, SRC, EGC), auditor name and PCAOB firm ID, fiscal year end | On `/profile` and the company page, each with its filing | S |
| **D-03** | **Derived ratios at query time** (ADR 0003 style, `derived=true`, inputs listed): gross/operating/net margin, free cash flow (OCF − capex), YoY growth, debt to equity, ROE, ROA, current ratio, book value per share | `GET /v1/companies/{cik}/facts?metric=fcf` and screen support them; never stored | S |
| **D-04** | **IFRS (`ifrs-full`) mapping** for the same 30 concepts; currency kept as reported (no FX) | 20-F filers such as TSMC, ASML, SAP return revenue and net income with currency; screen filters by currency | M |
| **D-05** | **8-K item events** on feed, SSE, webhooks and MCP: `sec.restatement` (4.02), `sec.auditor_change` (4.01), `sec.bankruptcy` (1.03), `sec.material_agreement` (1.01), `sec.acquisition_completed` (2.01), `sec.change_in_control` (5.01), `sec.results` (2.02), `sec.shareholder_vote` (5.07); plus `sec.late_filing` (NT 10-K/10-Q), `sec.deregistration` (Form 15), `sec.delisting` (Form 25), `sec.tender_offer` (SC TO-T), `sec.merger_proxy` (DEFM14A). Backfill never notifies (ADR 0004). | Watches can subscribe by type; webhook payload names the item and links the filing | S-M |
| D-06 | **Calendar alignment**: `calendar_period` (e.g. `CY2025Q3`) on facts, so screens compare companies with different fiscal years | Screen accepts `calendar_period` | S |
| I-01 | **VM, Compose, Caddy TLS, Cloudflare DNS**; Postgres on pgvector:pg16 with tuned memory (`shared_buffers` 2 GB, `effective_cache_size` 6 GB, `work_mem` 32 MB) | `/healthz` over HTTPS on the domain | S (owner + agent) |
| I-02 | **Fix `docs/deployment.md` cost and sizing** to the real database size and the VM plan, measured on the rebuilt local DB (not the old notes) | Doc matches reality | S |

### Hours 4-8: linkage, money, production data

| ID | Ticket | Acceptance | Effort |
|---|---|---|---|
| **K-01** | **CIK ↔ LEI ↔ ISIN**: GLEIF ISIN-to-LEI relationship file (confirm its licence, same as GLEIF's CC0 data) joined to FIRDS ISINs; SEC filer ↔ LEI by registered name + jurisdiction + address country, with `match_method` and `confidence`; manual overrides table | `/profile` shows LEI and listings on other venues; the company page links an ADR filer to its home listing (ASML, SAP, Shell); unmatched stays unmatched | M |
| K-02 | **Officer changes on insider edges** (connections.md #1): 8-K 5.02 appointed/departed dates end or start edges | "Current board" excludes departed people at once | S |
| K-03 | **Co-registrants** (connections.md #5): companies filing under one accession | Graph shows them; a utility holding company shows its utilities | S |
| K-04 | **Ticker and name history**: former names (stored) plus ticker changes seen in `company_tickers_exchange`; search finds a company by an old ticker | `search?q=FB` finds Meta with "formerly" | S |
| **G-01** | **Pricing in code** (approved 2026-11-22): one `PLANS` source of truth with every flag of §4. Enforce only what exists today: rate limit, quota, export rows, watches, event streams, chat per day, forecasts; `commercial_use` shown as a label. Seats, overage and agent credits are recorded as "with billing (G-02)" and stay hidden. `/v1/public/plans`, the pricing section, JSON-LD offers, the `/developers/` limits table and the quota error read from it. **New prices are not published until O-08.** | One source of truth; tests check site and API agree | S |
| **G-02** | **Checkout via the merchant of record**: hosted checkout link per plan and term; signed webhook → set account plan, store subscription ID, downgrade to free on cancel or failed payment; "Manage billing" link on `/account/`; agent credit packs as one-off products | Test-mode purchase upgrades a real account end to end; replayed or unsigned webhooks rejected | M |
| G-03 | **Legal pages**: plan-based commercial-use definition, attribution line ("Source: SEC EDGAR, via Provenance"), refund policy (the MoR requires one), data-sources page lists GLEIF/ESMA/FCA terms | Draft banner stays until the owner reads them; pages linked from checkout | S |
| I-03 | **Production data**: `pg_dump -Fc` of the local DB after D-01/D-04 reload, copy to the VM, `pg_restore -j 4`, `alembic upgrade head`, build marts, start poller and filings tracker | `/readyz` = ready; status page shows filings from today | M (owner runs, agent scripts) |
| I-04 | **Secrets and env**: new secrets per `docs/security.md`; `PUBLIC_BASE_URL`, `site/shell/site.json` origin, `sync_site_shell.py`; `MARKETS_DAILY_ENABLED`, `CONNECTIONS_DAILY_ENABLED`, `FILINGS_TRACKER_*` on | `readyz` lists no problems | S |
| I-05 | **Search embeddings in production**: already safe: `mode=semantic` falls back to keyword results with a note when the embedding model is unreachable (`routes_search.py`). Add a regression test; bge-m3 on CPU later if users want semantic search | No 500s from `/v1/search` | S |

### Hours 8-11: production hardening and smoke

| ID | Ticket | Acceptance | Effort |
|---|---|---|---|
| I-06 | **Backups (first, after the 2026-11-20 local data loss)**: local daily dump through launchd into `apps/provenance-backups` (keep 3), restore steps in `docs/operations.md`, a dump right after the rebuild; production nightly `pg_dump` to object storage (Backblaze B2 or Cloudflare R2), 14-day retention, one restore drill into a scratch DB | Drill restored and row counts match | S |
| I-07 | **Monitoring**: uptime check on `/readyz` every minute (free tier of an uptime service), `ALERT_WEBHOOK_URL` to the owner's own Telegram/Discord, error tracking (Sentry free tier) | One forced alert received | S |
| I-08 | **Load smoke**: 50 rps for 5 min on `/v1/companies/{cik}/facts`, `/v1/facts/screen`, `/v1/search`, `/mcp` | p95 < 500 ms on facts, < 2 s on screen; no errors | S |
| I-09 | **Production smoke script** `scripts/smoke_prod.py`: sign-up email arrives, key works, facts with `as_of`, webhook delivered to a receiver, SSE stream, MCP from Claude Code, checkout in test mode, demo limits | All green, output saved to `docs/pilot-report.md` | S |
| F-01 | **Google Sheets function** (GH #30, stretch): Apps Script `=PROVENANCE("AAPL","revenue","FY2025")` returning value + filing link note, user's key in script properties | Works in a fresh sheet; listed on `/developers/` | S |

### Hour 11-12: launch

| ID | Ticket | Acceptance |
|---|---|---|
| G-04 | Publish Python client `client-v0.1.0` (PyPI trusted publisher: owner) | `pip install` works |
| G-05 | Submit to the official MCP registry and community lists | Listing live or pending |
| G-06 | Show HN draft, outreach to the first 40 founders (`docs/launch-plan.md` copy, updated for the new plans and founding price) | Posted / sent by the owner |
| G-07 | Freeze: tag `v1.0.0`, changelog, close GH #31 items that are done | Tag pushed |

Buffer: hours 11-12 absorb overruns. If behind at hour 8, cut in this order: F-01, D-06, K-04,
K-03, D-04 (ship US-GAAP depth first). Never cut D-01, D-05, G-01, G-02, I-03, I-06, I-07.

---

## 4. Pricing (replaces Free / $49 / $199 / custom)

### What the market charges (checked 2026-11-22; verify before publishing)

| Vendor | Personal use | Commercial use (display in your app) |
|---|---|---|
| Financial Modeling Prep | $29 / $69 / $139 a month | separate display licence, contact sales |
| EODHD | fundamentals $59.99 a month | internal use $399, enterprise $2,499 a month |
| sec-api.io | about $55 a month | business internal use about $239; redistribution custom |

**The insight:** every competitor sells the data cheaply for personal use and charges 4-8x for
the right to show it to *your* users. Their sources are licensed; ours (SEC, GLEIF CC0, ESMA,
FCA) are public, so we can include commercial display at a mid-tier price. **"Commercial use
included from $79" is the wedge**, aimed straight at the AI-app builders in the launch plan.

What is wrong with the current prices: $49 is above the hobby price point (FMP $29) and far
below what commercial builders already budget ($239-$399); limits differ only by volume, so
nothing pushes a free user to pay; paying plans hard-stop at the quota instead of earning
overage; the design-partner deal gives 60 days free with no path to a price.

### Proposed plans

| | **Free** | **Analyst** | **Builder** | **Team** | **Enterprise** |
|---|---|---|---|---|---|
| Price, monthly | $0 | **$19** | **$79** | **$249** | from $1,500 |
| Price, billed yearly (per month) | $0 | $15 | $65 | $199 | annual only |
| Who | trying it | analysts, students, researchers | AI apps, fintech, dashboards | data teams, funds | resellers, platforms |
| Use | personal, non-commercial | personal | **commercial display with attribution** | commercial, internal + display | redistribution and resale |
| Requests a month | 10,000 | 50,000 | 500,000 | 3,000,000 | custom |
| Rate limit | 60/min | 120/min | 300/min | 1,000/min | custom |
| Overage | hard stop | hard stop | $0.50 per 1,000 (launches with billing) | $0.30 per 1,000 (launches with billing) | contract |
| All metrics, `as_of`, full history, MCP | yes | yes | yes | yes | yes |
| Chat questions a day | 20 | 200 | 500 | 2,000 | custom |
| Forecasts | no | yes | yes | yes | yes |
| Watches | 3, webhook (email with O-03) | 25, webhook (email with O-03) | 100, **webhooks + SSE (3)** | 1,000, webhooks + SSE (10) | custom |
| CSV export (bounded rows) | 100 rows | yes | yes | yes + graph export | bulk snapshots after legal review |
| Keys (seats with billing) | 2 | 2 | 5 | 20 | SSO, custom |
| Support | docs | email | email, 2 business days | priority, 1 business day | SLA |

**Agent credits (no subscription; launches with billing):** $10 for 20,000 calls, valid 12 months, commercial use with
attribution, at most 120/min. For MCP and agent builders who will not subscribe; sold as one-off
products through the merchant of record. Pay-per-call (x402) later.

**Launch offers**
- **Founding customers:** first 25 paid accounts get **50% off for 12 months on an annual plan**
  (Builder $390 for the first year). This replaces "Builder free for 60 days": it brings cash,
  and a yes is a willingness-to-pay signal, which is what AGENTS.md §16 measures.
- **Design partners (10):** Builder free for 30 days, then the founding price; the bi-weekly call
  stays.
- Students and academics: Analyst free with an .edu or .ac address (applied by hand).

**Rules that keep it honest**
- Nothing that is free today disappears silently: existing `pilot` keys keep Builder limits
  until 2027-01-31, then move to Builder at the founding price or Free.
- Attribution is required on Free, Builder and agent credits: "Source: SEC EDGAR, via
  Provenance" with a link. It is also free marketing.
- No feature that protects data quality is ever paywalled: `quality_status`, citations and
  `as_of` are on every plan.

### Revenue frame (planning, not data)

20 Analyst + 8 Builder + 2 Team at month 3 = $380 + $632 + $498 ≈ **$1.5k MRR**, against a
hosting + model + email cost under $60 a month. One Enterprise or reseller deal doubles it.
Compare the earlier frame of about $250 MRR at 3 months on the old prices.

---

## 5. After launch (weeks 1-4, in order)

1. **13F institutional holders** (GH #24, connections.md #4): who owns the company each quarter.
   CUSIPs are licensed by CGS: use them only internally to join 13F to CIK, never return them.
2. **Segments and ~100 line items** (GH #25), building on D-01.
3. **Guidance quoted from 8-K 2.02 releases** (GH #26).
4. **"First reported" timestamp**: link each figure to the 8-K 2.02 earnings release that
   announced it before the 10-Q, so `as_of` reflects what the market knew on release day.
   Quants will pay for this; nobody at this price does it.
5. Insider signals (cluster buys, first purchase in years, 10b5-1 vs discretionary) as event
   types and webhooks (connections.md #2): Builder-plan material.
6. Auditor graph from PCAOB Form AP (connections.md #8) and the 4.01 events from D-05.
7. Person view (connections.md #3) only after legal review for EU/UK visitors.
8. Prices via the user's own key (GH #29) so valuation ratios work without us licensing prices.

## 6. Metrics to watch from day 1

Existing `scripts/pilot_metrics.py` plus: checkout started → paid conversion, free → paid
within 14 days, overage revenue, share of keys with `commercial_use`, webhook deliveries per
paid account, and model spend per paid account (must stay under 10% of its price).
