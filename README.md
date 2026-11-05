# Provenance

US public-company filings data API.

Developer-first API for US public-company identity, SEC filings, normalized XBRL financial
facts, freshness tracking, signed filing notifications, API-key onboarding and bounded exports.
Built only on official SEC EDGAR endpoints. Independent of, and not affiliated with, the SEC.

The implementation contract is `AGENTS.md`. Deviations from it are listed at the end of this
file.

## What it does

| Capability | Endpoint |
| --- | --- |
| Company lookup by ticker, CIK or name | `GET /v1/companies/search?q=` |
| Company list with filters (exchange, SIC, state, ingested) | `GET /v1/companies` |
| Cross-company screen: rank one metric across all companies for a year or quarter; `/v1/facts/screen/periods` lists the years and quarters with data | `GET /v1/facts/screen?metric=&year=&period=quarterly&quarter=` |
| Company profile, on-demand ingestion (`202`) | `GET /v1/companies/{cik}` |
| Search: companies by name or ticker, plus passages of stored filing sections by keyword or meaning (semantic needs your own key), each linked to its filing | `GET /v1/search?q=&mode=keyword\|semantic` |
| Readable company profile in Markdown, every figure linked to its filing, with a short cited summary (the chat answers "summarise X" from it) | `GET /v1/companies/{cik}/profile` |
| Recent filings with SEC source links and honest timestamps | `GET /v1/companies/{cik}/filings` |
| Normalized facts: revenue, operating income, net income, total assets, operating cash flow | `GET /v1/companies/{cik}/facts` |
| Point-in-time facts and screen: only what had been filed by a date, for backtests | `?as_of=YYYY-MM-DD` on `/facts` and `/v1/facts/screen` |
| Freshness: fetch age, detection/processing times, status | `GET /v1/companies/{cik}/freshness` |
| Event feed: new SEC filings and listing events, ordered and resumable, by polling or Server-Sent Events | `GET /v1/events?after=`, `GET /v1/events/stream` |
| Watches and signed webhook deliveries | `POST/GET/DELETE /v1/watches`, `GET /v1/watches/{id}/deliveries` |
| API keys and usage | `POST/GET/DELETE /v1/developer/api-keys`, `GET /v1/developer/usage` |
| Bounded CSV/JSON export with provenance | `GET /v1/exports/facts` |
| Explorer web app: search, filings, facts chart with provenance, freshness | `GET /app/` (static, key stays in the browser) |
| Developer console: usage and plan meters, keys, watches, deliveries | `GET /app/#console` |
| Public coverage stats, cached 30 s, no key | `GET /v1/stats` |
| Public showcase API: plans, companies, per-company bundle (no key, cached 60 s, never calls the SEC) | `GET /v1/public/plans`, `/v1/public/companies`, `/v1/public/companies/{cik}` |
| Public pages driven by the API: directory, company pages, status | `GET /companies/`, `/companies/{cik}`, `/status/` |
| International listings (Canada, Europe, UK): venues, issuers (LEI), instruments, new listings / delistings / suspensions / name changes | `GET /v1/markets/`, `/v1/markets/instruments`, `/v1/markets/instruments/{isin}`, `/v1/markets/events`, `/v1/markets/issuers/{lei}` |
| API playground with the public `demo` key (read-only, showcase companies, 10 rows, 20 req/min) | `GET /playground/` |
| Company-intelligence chat: cited brief from SEC data (annual metrics with growth, recent filings, 8-K item 5.02 leadership changes), phrased by a local language model (Ollama, Qwen3 4B Instruct) and checked against the data | `POST /v1/chat`, page `/chat/` |
| 8-K item codes on filings (e.g. 5.02 officer changes) | `items` on `/filings` and on the event feed |
| Python client: companies, point-in-time facts, screen, listings, event feed (polling and SSE), DataFrames | `clients/python` |
| Health | `GET /healthz`, `GET /readyz` |
| Marketing site POC with pilot pricing, `llms.txt` for agents | `GET /`, `GET /llms.txt` (static files in `site/`) |
| Universe: seed CIKs, budgeted resumable bulk ingestion with backoff | `scripts/bulk_ingest.py`, poller refreshes due members |
| All public companies from SEC nightly bulk archives (submissions.zip, companyfacts.zip) | `scripts/sec_bulk.py` |
| Quality snapshots per run, SEC request metrics, retention purge | `scripts/quality_report.py`, `scripts/retention.py`, `/v1/stats.quality_snapshot` |

OpenAPI: `/openapi.json`, Swagger UI: `/docs`. All `/v1` endpoints require `X-API-Key`.

## Quick start (local)

Requirements: Python 3.12+, [uv](https://docs.astral.sh/uv/) (or pip), Docker for PostgreSQL.

```bash
cd provenance
cp .env.example .env
# edit .env: SEC_USER_AGENT (your product + a monitored contact email),
#            API_KEY_PEPPER and WEBHOOK_SIGNING_SECRET (python -c "import secrets;print(secrets.token_urlsafe(48))")

uv venv --python 3.12 .venv && uv pip install -e ".[dev]"   # or: python -m venv .venv && .venv/bin/pip install -e ".[dev]"
source .venv/bin/activate

docker compose up -d db                 # PostgreSQL 16 with pgvector on localhost:5432
alembic upgrade head                    # apply migrations

python scripts/create_api_key.py you@example.com --plan builder   # prints the key once
python scripts/import_tickers.py        # optional: seed ~10k company identities from the SEC ticker file
python scripts/ingest_company.py 320193 # ingest one company (filings + facts) from the SEC

# all public companies from the SEC nightly bulk archives (2 SEC requests, each file over 1 GB)
python scripts/sec_bulk.py --download
python scripts/sec_bulk.py --scope facts --dry-run   # how many XBRL filers (about every operating public company)
python scripts/sec_bulk.py --scope facts             # ingest them all through the same pipeline as the API path

# bulk coverage: define a universe, then ingest it within an SEC request budget (resumable)
python scripts/bulk_ingest.py --seed-file data/universe.sample.txt --seed-only
python scripts/bulk_ingest.py --seed-tickers --top 500 --seed-only   # or the first 500 issuers of the SEC ticker file
python scripts/bulk_ingest.py --budget 400 --history-pages 1          # one pass; re-run until --status shows due_now 0
python scripts/bulk_ingest.py --status
python scripts/quality_report.py --take     # data-quality snapshot + trend (AGENTS.md section 12 metrics)

# international listings (ESMA FIRDS, FCA FIRDS, GLEIF; TSX/CSE only if you hold permission)
python scripts/ingest_markets.py --all              # daily: last 3 days of FIRDS deltas + GLEIF enrichment
python scripts/ingest_markets.py --source esma_firds --full --days-back 8   # one-off weekly full equities file
python scripts/retention.py                 # purge usage/deliveries past the retention windows

uvicorn app.main:app --reload           # http://127.0.0.1:8000/docs
python scripts/poll_sec.py --once       # refresh watched companies, deliver pending webhooks
```

Without Docker, set `DATABASE_URL=sqlite:///./dev.sqlite3` in `.env` for a local experiment.
SQLite is refused in production.

### Test a webhook end to end

```bash
# terminal 1: receiver (verifies HMAC signatures)
WEBHOOK_SECRET=<webhook_secret from POST /v1/watches> python scripts/webhook_receiver.py 8081
# API + poller need WEBHOOK_ALLOW_PRIVATE_DESTINATIONS=true locally to accept http://127.0.0.1
curl -H "X-API-Key: $API_KEY" -H 'Content-Type: application/json' -X POST localhost:8000/v1/watches \
  -d '{"cik":"320193","destination_type":"webhook","destination":"http://127.0.0.1:8081/"}'
python scripts/poll_sec.py --once      # delivers events for newly detected filings
```

Webhook requests carry `X-Event-Id`, `X-Signature-Timestamp` and
`X-Signature: v1=<hex HMAC-SHA256(secret, "<timestamp>.<body>")>`. Verification code is in
`examples/client.py` and `scripts/webhook_receiver.py`. Events are at-least-once with a stable
`event_id`; deduplicate on it.

## Tests

```bash
ruff check app tests scripts && ruff format --check app tests scripts
pytest                                   # SQLite, no network: 141 tests
# against PostgreSQL: use a dedicated database, the suite drops and recreates all tables
docker compose exec db createdb -U companydata companydata_test
TEST_DATABASE_URL=postgresql+psycopg://companydata:companydata@localhost:5432/companydata_test pytest
SEC_LIVE_TESTS=1 pytest tests/integration/test_live_sec_smoke.py   # optional, hits the SEC once
```

Verified on 2026-10-17: `ruff` clean; `pytest` 141 passed / 1 skipped on SQLite and on
PostgreSQL 16; `alembic upgrade head` and `downgrade base` succeed on an empty SQLite and
PostgreSQL 16 database. The dedicated live SEC smoke test was **not** run. During a local smoke
run, an on-demand `GET /v1/companies/320193` did reach the real SEC (two requests) and ingested
Apple's recent filings and facts successfully, so the live path is known to work end to end;
that database was discarded. `/readyz` now reports `not_ready` when the `SEC_USER_AGENT`
contact address is a placeholder domain, to prevent accidental live calls with a non-monitored
address.

## API examples

Full samples: `examples/curl.sh`, `examples/client.py`.

```bash
curl -H "X-API-Key: $API_KEY" "localhost:8000/v1/companies/search?q=AAPL"
curl -H "X-API-Key: $API_KEY" "localhost:8000/v1/companies/320193/filings?form_type=10-K&limit=5"
curl -H "X-API-Key: $API_KEY" "localhost:8000/v1/companies/320193/facts?metric=revenue&period=annual"
curl -H "X-API-Key: $API_KEY" "localhost:8000/v1/companies/320193/freshness"
curl -H "X-API-Key: $API_KEY" "localhost:8000/v1/search?q=use%20of%20proceeds&form=S-1"
curl -H "X-API-Key: $API_KEY" "localhost:8000/v1/companies/320193/profile"
curl -H "X-API-Key: $API_KEY" -o facts.csv "localhost:8000/v1/exports/facts?metric=revenue&ciks=320193&format=csv"
```

A fact looks like this (values illustrative):

```json
{
  "metric": "revenue", "value": 391035000000, "unit": "USD", "currency": "USD",
  "period_start": "2023-10-01", "period_end": "2024-09-28", "period_type": "duration", "period_class": "annual",
  "fiscal_year": 2024, "fiscal_period": "FY", "form_type": "10-K", "filed_date": "2024-11-01",
  "accession_number": "0000320193-24-000123",
  "source_tag": "RevenueFromContractWithCustomerExcludingAssessedTax", "source_taxonomy": "us-gaap",
  "source_url": "https://www.sec.gov/Archives/edgar/data/320193/000032019324000123/0000320193-24-000123-index.html",
  "mapping_version": "1.1.0", "quality_status": "ok", "derived": false,
  "revision_count": 1, "processed_at": "2026-10-17T12:05:02Z"
}
```

Errors always use `{"error": {"code", "message", "request_id"}}`; every response carries
`X-Request-ID`. Rate limits return `429` with `Retry-After`.

### Local language model (chat)

The chat works without a model: it returns the cited data brief. To add written answers, run
[Ollama](https://ollama.com) on the same host or network, `ollama pull qwen3:4b-instruct`, and set
`LLM_ENABLED=true` (optional: `LLM_BASE_URL`, `LLM_MODEL`). The model sees only the brief, never
the internet, and every answer is checked: citations must exist and every number must appear in
the cited data, or the reply is flagged. Measured on an M4 Pro: about 2.5 to 6 s per answer.

Leadership questions ("What are the recent leadership changes at Microsoft?") are answered from
8-K item 5.02 text. The first time a filing is needed, its item 5.02 section is fetched from
EDGAR (needs `SEC_USER_AGENT`) and stored; the model lists who, role, what changed, effective
date, stated reason and successor. A person whose name is not in the text is dropped, and each
row is traced to the filing sentence it came from, or marked unverified. The public demo key
never triggers these fetches. `scripts/read_officer_changes.py --cik ...` reads ahead of time.

Companies going public have no annual XBRL figures yet; their numbers are in the prospectus.
When a company has no annual figures, or the question is about an offering or its risks, the
chat quotes its latest S-1, F-1 or final prospectus (424B). The document is fetched once, cut
into its main sections by the table of contents (summary, risk factors, use of proceeds,
capitalization, dilution, MD&A, business, management, executive compensation, principal
stockholders, underwriting) and stored in `filing_sections`. A question gets the company
overview, the summary financial table with every figure labelled by its period, and the
passages that match it best, each cited to the filing and section. The demo key answers about
every loaded company from stored data and never fetches; `scripts/read_prospectuses.py --cik
...` or `--recent-days 30` reads documents ahead of time.

Questions across companies are answered from precomputed tables without the model, usually in
well under a second. Examples: "How many new listings in the last 6 months?", "Who filed a 10-K
this week?", "Top 5 companies by revenue". A reply carries a `context` (the companies it listed,
or the company in focus); sending it back with the next question, along with the last few
exchanges in `history`, lets a follow-up such as "show me their revenue for the last 3 years in
a table" use the previous answer. A plain figure question ("What was Apple's revenue last year?")
is also answered from the data. Model answers are kept short and cleaned of chatbot residue
(greetings, recaps, "the context"); `CHAT_HUMANIZE=false` turns the clean-up off.

Stored filing sections are also searchable by meaning (ADR 0008). `python
scripts/embed_sections.py --model bge-m3` cuts them into chunks and embeds them with a local Ollama
model into `section_chunks` (pgvector, HNSW index); `app/services/semantic_search.py` searches
them by vector, keyword or both, within a company or across all, with a filing date cutoff.
`python scripts/bench_search.py` reruns the 30-question benchmark in `docs/benchmarks/`.

The tables are `mart_company` (one row per company: filing history, going-public dates, latest
annual figures and five years of revenue, each with its filing) and `mart_filing_activity`
(filings per month and form), plus `mart_financials` and `mart_company_period` (one value per
period with fiscal labels; ADR 0009) and `company_documents` (a readable Markdown profile per
company). `python scripts/build_marts.py` rebuilds them all in about four minutes on 20,000
companies; ingestion refreshes a company's rows as it runs. "Summarise Microsoft" is answered
from the profile's cited sentences without the model (`intent: "summary"`, about 0.1 s).

Forecast questions ("Forecast Microsoft revenue for the next 4 years", "What is the outlook for
Apple net income?") get `intent: "forecast"` and a forecast chart widget. The evidence is cited
like any answer: the reported annual figures, the latest quarter against the same quarter a year
earlier, the opening of the latest earnings release (8-K item 2.02, exhibit 99.1, fetched once
and stored), and recent headlines about the company and its industry (Google News RSS, chosen by
SIC code; headline, publisher, date and link only, cached for `NEWS_CACHE_HOURS`). A reasoning
model (`LLM_REASONING_MODEL`, default `qwen3:30b-a3b`) thinks over it, then states growth rates
for a base, low and high case with drivers and risks as JSON. The model never writes a dollar
figure: every projected value is computed here from its rates (bounded to -60%..+150% a year),
and a driver or risk that cites nothing real or carries a number not in the evidence is dropped.
Without the model the rates come from the trend alone and the reply says so. The demo key never
fetches: it uses stored releases and fresh cached headlines only. Google News RSS is for
personal, non-commercial use; a commercial deployment plugs a licensed provider into
`app/services/news.py`. About 30 to 60 s per forecast on an M4 Pro.

With your own API key, conversations are saved per key (`chat_sessions`, `chat_messages`) and
listed at `GET /v1/chat/sessions`; the `/chat/` page shows them in its sidebar and restores the
open one from the URL (`#s=<id>`). The demo key saves nothing on the server.

Questions about a figure over time ("How has Apple's revenue grown over the last 5 years?") are
answered from the data, not the model: the reply's `widgets` carries a chart of the reported
annual figures (one cited 10-K figure per fiscal year; N years of growth uses N + 1 figures) with
the year-on-year change, compound annual growth, best and weakest year, all computed here and
labelled as computed. Other company questions get tiles of the latest annual figures. `intent`
says how the question was read (`leadership`, `trend` or `question`). The page draws charts with
Chart.js 4.4.7 (MIT), vendored in `site/vendor/chartjs-4.4.7/` and loaded only when needed; the
figures are also listed as a table with sources.

### Facts semantics worth knowing

- `period=annual|quarterly|all` filters on `period_class`, which is computed from the reported
  period dates. A 6- or 9-month year-to-date value is `ytd`, never a quarter, even though the
  SEC labels it `fp=Q2/Q3`.
- Default view returns one observation per period (latest filed, preferred tag) with
  `revision_count`. `include_all_observations=true` returns restatements and alternate tags.
- `include_derived=true` adds standalone quarters computed as `YTD(n) - YTD(n-1)` with
  `derived=true`, `quality_status=derived` and the two source observations in `derivation`.
- Absent facts are absent. Unparseable values are `null` with `invalid_source_value`.
- `as_of=YYYY-MM-DD` answers as of that date: observations filed after it (and observations
  without a filing date) are ignored, so a later restatement is invisible and `revision_count`
  counts only revisions known then. `filed_date` has no time of day, so a filing accepted after
  the close on `as_of` is included; pass the previous day for a strict backtest.
- Mapping 1.1.0 judges tag conflicts within one filing. Before, a later restatement could mark
  an earlier filing's observation `ambiguous_mapping` with hindsight. Stored rows pick up the
  new version on their next ingestion.

## Onboarding

Visitors request a key from the landing page (`POST /v1/developer/key-requests`: public,
per-IP rate limited, honeypot, one pending request per email). An operator reviews with
`scripts/approve_key_request.py list|approve|reject`; `approve --email` sends the key when SMTP
is configured, otherwise the key is printed once for manual delivery. Deviation from ticket 08:
there is no email-verification auto-approval; every request is approved by a person. Operators can also issue
keys directly via `scripts/create_api_key.py` or `POST /v1/developer/api-keys` protected by
`X-Admin-Token` (disabled unless `ADMIN_TOKEN` is set). Key holders can list and revoke keys that share their
owner email. Plans: `free` (60 req/min, 10k req/month, 5 watched companies), `builder` (300/min,
250k/month, 50 watches), `team` (1,000/min, 2M/month, 500 watches), `enterprise`, `internal`; all
capped at 1,000 export rows per request. Limits live in `PLAN_LIMITS` and match the pricing page.

## Deployment

See `docs/deployment.md` for Fly.io (`deploy/fly.toml`), Render (`deploy/render.yaml`) and
Docker Compose paths with commands and planning costs, and `docs/operations.md` for topology,
secret rotation, backups, monitoring and retention. `Dockerfile` serves the API; the poller runs
the same image with `python scripts/poll_sec.py`.

## Documentation

- `docs/data-dictionary.md`: every column and status, the concept mapping and precedence rule.
- `docs/data-rights.md`: sources, attribution, exclusions, limitations notice, open legal questions.
- `docs/operations.md`: run book.
- `docs/implementation-checklist.md`: what was built, in priority order.

## International listings

Since ADR 0006 the API also tracks listing lifecycle for Canada, the EU/EEA and the UK:
venues (MIC), issuers (LEI via GLEIF), instruments (ISIN on a venue) and events
(`new_listing`, `delisting`, `suspended`, `reinstated`, `modified`, and `ipo` only when a
source states it). Sources and their terms are in `docs/research/international-listings-sources.md`
and `docs/data-rights.md`. ESMA FIRDS, FCA FIRDS and GLEIF are enabled by default; the TSX and
CSE adapters exist but are disabled because their terms are non-commercial. A `new_listing` is
an instrument first trading on a venue; the API never calls it an IPO.

## Known limitations

- By default only the `recent` block of SEC submissions (about the latest 1,000 filings per
  company) is ingested. Set `SEC_FILINGS_HISTORY_PAGES` (or `--history-pages`) to pull older
  pages; each page is one more SEC request per company.
- Facts use standard `us-gaap` tags from the SEC company-facts API; IFRS filers and custom
  extension tags are not covered.
- `source_published_at` is always `null`; the SEC exposes an acceptance timestamp, not a
  dissemination timestamp. `publication_to_detection_seconds` is therefore never computed;
  `acceptance_to_detection_seconds` is provided instead when `accepted_at` exists.
- Detection latency is bounded by the poll interval (default 300 s) and SEC propagation; no SLA.
- Email notifications are implemented behind an SMTP adapter but disabled unless
  `EMAIL_PROVIDER=smtp` is configured; creating an email watch returns a clear error otherwise.
  They have not been exercised against a real SMTP server.
- Rate limiting is in-process; multiple API replicas multiply the effective limit. Per-IP limits rely on uvicorn's `--proxy-headers --forwarded-allow-ips` (set in the Dockerfile and deploy manifests); without them every visitor behind a proxy shares one bucket.
- SEC request metrics are per-run totals (requests, retries, errors, 304s, duration), not per endpoint or per status code.
- SSRF protection validates at creation and re-resolves DNS immediately before each delivery,
  but the HTTP client still connects by hostname, leaving a small rebinding window.
- Company search uses `LIKE` with a bounded scan; no trigram index yet.
- Retention purges run from `scripts/retention.py`; schedule it (daily cron) yourself, it is not automatic.
- Coverage is limited to companies that have been ingested; nothing is "complete".
- Listings: FIRDS first-trade dates are per instrument and venue, so secondary-venue admissions
  look like new listings; issuer names are instrument names until GLEIF enrichment runs (bounded
  to 50 lookups per run); Canadian rows have no ISIN and the Canadian adapters are off by
  default. Live check on 2026-10-22: one ESMA delta part (DLTINS_20261021_04of04) parsed in 13 s
  and produced one covered equity record and a delisting event; GLEIF enrichment resolved the
  issuer. A full daily pass processes all delta parts (about 4 per day per register).
- The public website exposes only the showcase set (`PUBLIC_SHOWCASE_CIKS`, or the most
  recently filed ingested companies up to `PUBLIC_SHOWCASE_LIMIT`), annual facts only, and
  never triggers SEC requests. Pricing on the site is read from `/v1/public/plans`.

## Deviations from AGENTS.md (and why)

- **Extra columns**: `companies.last_successful_fetch_at/last_fetch_error(_at)` (stale
  reporting after SEC outages), `filings.report_date/primary_document`,
  `financial_facts.period_class/source_taxonomy/derivation/observation_key` (query efficiency,
  explicit derivation provenance, a NULL-safe unique key), `api_usage.export_rows` (export
  metering), `audit_events` table (required audit trail).
- **Webhook secrets are derived**, not stored: `HMAC(WEBHOOK_SIGNING_SECRET, watch_id)`. Only the
  hash is persisted, so the raw secret never sits in the database; rotating the master secret
  invalidates all watch secrets.
- **Derived quarters are computed at query time**, not stored, to keep the facts table a pure
  record of reported observations.
- **SQLite is supported for tests and local experiments**; production requires PostgreSQL.
- **Backfill does not fan out notifications**: filings discovered during a company's first
  ingestion do not create events; only filings detected afterwards do.
- **`pip-audit`** was dropped from the dev extras after repeated PyPI timeouts during setup;
  run it separately (`uvx pip-audit`) before deploying.
