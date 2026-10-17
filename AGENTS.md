# AGENTS.md --- US Public Company Filings Data API

> **Purpose:** Implementation contract for coding agents building a
> small, developer-first API for US public-company identity, SEC
> filings, normalized financial facts, freshness tracking, filing
> notifications, API onboarding, and limited bulk exports.
>
> **MVP constraint:** Seven calendar days of implementation; initial
> cash spend below ₹25,000 INR; use official SEC sources; do not use
> paid market-data feeds or redistribute third-party data without
> appropriate rights.
>
> **Product promise:** Make official public-company filing information
> easier to discover, normalize, monitor, and consume through a
> documented API. Do not promise exchange-grade real-time market data.

------------------------------------------------------------------------

## Agent skills

This repo is configured for the engineering skills (`to-tickets`, `implement`, `triage`, `to-spec`):

- Issue tracker: local markdown, see `docs/agents/issue-tracker.md`.
- Triage labels: defaults, see `docs/agents/triage-labels.md`.
- Domain docs: single context; `GLOSSARY.md` and `docs/adr/`, see `docs/agents/domain.md`.

Product working name: **Provenance**. The contract below predates the name.

------------------------------------------------------------------------

## 1. Instructions to the coding agent

You are implementing a production-minded MVP, not a throwaway demo.
Prioritize correctness, provenance, safe defaults, a working vertical
slice, and clear limitations over breadth.

### Non-negotiable rules

1.  **Use official SEC sources only for the core MVP data ingestion.**
    Primary sources:
    -   SEC company submissions JSON:
        `https://data.sec.gov/submissions/CIK##########.json`
    -   SEC company facts XBRL JSON:
        `https://data.sec.gov/api/xbrl/companyfacts/CIK##########.json`
    -   SEC filing archive URLs derived from accession number and CIK,
        with the SEC filing index as the human-readable source.
    -   SEC ticker/exchange association file where available:
        `https://www.sec.gov/files/company_tickers_exchange.json`
2.  Follow SEC fair-access guidance. Send a descriptive `User-Agent`
    with product name and a monitored contact email. Respect rate
    limits, use bounded concurrency, cache responses, and implement
    exponential backoff for `429` and transient `5xx` responses. Do not
    attempt to bypass throttling.
3.  **Do not invent data.** Missing facts remain absent/null, not zero.
    Preserve source facts and disclose the mapping logic used to produce
    normalized fields.
4.  **Do not silently overwrite history.** Store ingestion events and
    source timestamps. Upsert current records idempotently while
    retaining the first-detected timestamp and revision history where
    practical.
5.  **Do not describe SEC filing data as real-time stock prices.** This
    MVP does not provide quotes, intraday prices, trading signals,
    investment advice, or guaranteed event detection latency.
6.  **Do not scrape or redistribute paid vendor datasets.** SEC
    availability does not grant rights to every third-party dataset.
    Exclude exchange market prices, analyst estimates, consensus data,
    newswire content, and vendor-enriched datasets from this MVP.
7.  Never expose API keys, webhook secrets, database credentials, raw
    internal errors, or full environment configuration to clients.
8.  All API endpoints must be documented in OpenAPI and covered by
    automated tests.
9.  Prefer a simple implementation that can be completed in seven days.
    Do not add Kafka, Kubernetes, microservices, a vector database, an
    LLM dependency, or a complex frontend.
10. If an upstream SEC field is missing or ambiguous, preserve the raw
    source reference and return a clear null/quality status instead of
    guessing.

### Agent workflow

-   Inspect the repository before making changes.
-   Create or update a concise `README.md`, `.env.example`, database
    migrations, tests, and this `AGENTS.md` if needed.
-   Implement one end-to-end vertical slice first: ingest company →
    ingest filings/facts → query API → record freshness → notify a test
    webhook → export facts.
-   Run formatting, linting, unit tests, and integration tests before
    marking a task complete.
-   Do not claim a test passed unless it was executed.
-   Keep secrets out of Git. Add `.env`, `.env.*` (except
    `.env.example`), local databases, generated exports, and caches to
    `.gitignore`.
-   When an implementation choice differs from this specification,
    document the deviation and reason.

------------------------------------------------------------------------

## 2. Product scope

### Included MVP capabilities

1.  **Company lookup**
    -   Search by ticker, SEC CIK, or company name.
    -   Return canonical company identity and source metadata.
2.  **Recent filings**
    -   List recent SEC filings for a company.
    -   Return form type, filing date, accepted timestamp when
        available, source URL, accession number, and source timestamps.
3.  **Normalized financial facts**
    -   Standardized revenue, operating income, net income, assets, and
        cash flow where disclosed.
    -   Preserve units, currency, fiscal period, form, accession/source
        references, and mapping metadata.
4.  **Freshness tracking**
    -   Record source timestamp where supplied, first detection time,
        processing completion time, and a data-quality status.
    -   Make latency measurable; do not promise a fixed SLA during MVP.
5.  **Change notifications**
    -   Notify a registered webhook or email destination when a watched
        company has a newly detected filing.
    -   Deliver at-least-once with deduplication keys; retry failures
        and show delivery status.
6.  **Developer onboarding**
    -   API key creation/revocation, usage metering, OpenAPI schema, and
        sample code.
7.  **Limited bulk export**
    -   Download a bounded set of normalized financial facts as CSV or
        JSON.
    -   Enforce row/size limits and usage accounting.

### Explicitly out of scope

-   Live or delayed stock quotes, EOD prices, OHLCV, intraday data,
    order books, corporate-action price adjustments.
-   Investment recommendations, valuation models, buy/sell signals, or
    financial advice.
-   Analyst estimates, consensus estimates, news, transcripts, or
    third-party proprietary datasets.
-   Broad non-US issuer coverage.
-   Guaranteed low-latency or guaranteed completeness of SEC updates.
-   User-defined arbitrary SQL, unrestricted bulk mirrors, unlimited
    exports, or unrestricted historical data downloads.
-   Multi-tenant workflow marketplace, AI-agent purchasing, MCP server,
    mobile apps, complex admin UI, and custom enterprise SLAs.
-   Automated interpretation of every custom XBRL taxonomy in the MVP.
-   Any assertion that the service is endorsed by or affiliated with the
    SEC.

------------------------------------------------------------------------

## 3. Primary users and user stories

### Target users

-   Fintech and research developers who need SEC filing facts in a
    consistent schema.
-   Small financial analytics SaaS products.
-   AI application developers who need source-linked company facts.
-   Analysts and data teams monitoring a defined list of public
    companies.

### User stories

-   As a developer, I can find a company by ticker, CIK, or name and
    receive a stable company identifier.
-   As a developer, I can retrieve a company's latest filings with
    direct source links and available timestamps.
-   As a developer, I can query normalized financial facts without
    manually parsing raw XBRL JSON.
-   As a user, I can see when a filing was published (when available),
    first detected by this system, and processed.
-   As a user, I can subscribe to filing notifications for selected
    companies and receive a deduplicated event.
-   As a developer, I can create and revoke API keys, inspect usage, and
    try requests using documented sample code.
-   As a developer, I can export a limited dataset and know which source
    fact and mapping produced each row.

------------------------------------------------------------------------

## 4. Proposed technology stack

Keep the stack deliberately small.

-   **Language/runtime:** Python 3.12+
-   **API:** FastAPI
-   **Validation and settings:** Pydantic v2 and pydantic-settings
-   **HTTP client:** `httpx`
-   **Database:** PostgreSQL (managed or local for development)
-   **ORM/migrations:** SQLAlchemy 2 + Alembic
-   **Scheduling:** a single scheduled worker/cron job; no queue
    infrastructure required for MVP
-   **Email:** provider adapter (e.g., Resend or SMTP) configured only
    when credentials exist
-   **Webhook delivery:** `httpx` with timeout, retry, and delivery
    records
-   **CSV:** Python standard library or pandas only if useful
-   **Tests:** pytest, pytest-asyncio if async tests are used, and httpx
    TestClient
-   **Formatting/linting:** Ruff
-   **Deployment:** one API service + one scheduled ingestion process +
    managed PostgreSQL, or one process with a scheduler for the demo.
    Prefer separate API and ingestion commands in code.
-   **Docs:** FastAPI-generated OpenAPI at `/openapi.json` and Swagger
    UI at `/docs`.

Do not add Redis, Celery, Kafka, Kubernetes, or a frontend framework in
the MVP. A minimal server-rendered developer page is optional; the API
and docs are the priority.

### Suggested repository layout

``` text
.
├── app/
│   ├── main.py
│   ├── api/
│   │   ├── dependencies.py
│   │   ├── routes_companies.py
│   │   ├── routes_filings.py
│   │   ├── routes_facts.py
│   │   ├── routes_notifications.py
│   │   ├── routes_exports.py
│   │   └── routes_developer.py
│   ├── core/
│   │   ├── config.py
│   │   ├── security.py
│   │   ├── rate_limits.py
│   │   └── logging.py
│   ├── db/
│   │   ├── models.py
│   │   ├── session.py
│   │   └── migrations/
│   ├── schemas/
│   ├── services/
│   │   ├── sec_client.py
│   │   ├── ingestion.py
│   │   ├── company_lookup.py
│   │   ├── fact_normalizer.py
│   │   ├── freshness.py
│   │   ├── notifications.py
│   │   ├── exports.py
│   │   └── usage.py
│   ├── jobs/
│   │   └── poll_sec.py
│   └── templates/             # optional minimal onboarding page
├── tests/
│   ├── unit/
│   ├── integration/
│   └── fixtures/
├── scripts/
│   ├── ingest_company.py
│   ├── poll_sec.py
│   └── create_api_key.py
├── docs/
│   ├── data-dictionary.md
│   ├── data-rights.md
│   └── operations.md
├── .env.example
├── .gitignore
├── alembic.ini
├── pyproject.toml
├── Dockerfile
├── docker-compose.yml          # local development only
├── README.md
└── AGENTS.md
```

------------------------------------------------------------------------

## 5. Data sources and ingestion design

### 5.1 SEC endpoints

Use the SEC's official public endpoints. Confirm current SEC technical
guidance before deployment.

-   Company submissions:
    `https://data.sec.gov/submissions/CIK{cik_padded_to_10_digits}.json`
-   Company facts:
    `https://data.sec.gov/api/xbrl/companyfacts/CIK{cik_padded_to_10_digits}.json`
-   Ticker/exchange mapping:
    `https://www.sec.gov/files/company_tickers_exchange.json`
-   Filing archive:
    `https://www.sec.gov/Archives/edgar/data/{cik_without_leading_zeroes}/{accession_number_without_hyphens}/{accession_number_with_hyphens}-index.html`

Use only SEC-hosted URLs and records for this MVP. Do not assume every
issuer has every endpoint or every desired fact.

### 5.2 SEC HTTP client requirements

-   Set `User-Agent: <ProductName>/<version> contact=<monitored email>`.
-   Set connection and read timeouts.
-   Set conservative request rate and bounded concurrency; start at no
    more than 5 requests/second per deployment unless current SEC
    guidance requires less.
-   Cache unchanged responses using ETag/Last-Modified when supported.
-   Retry `429`, `500`, `502`, `503`, and `504` with exponential backoff
    and jitter, respecting `Retry-After`.
-   Do not retry ordinary `4xx` except `408` and `429`.
-   Log endpoint, status code, duration, retry count, and request
    correlation ID; never log secrets.
-   Use a shared rate limiter between scheduled ingestion workers where
    more than one worker could run.
-   If SEC is unavailable, retain the last successful data, record the
    failed attempt, and report the data as stale rather than fabricating
    freshness.

### 5.3 Ingestion workflow

1.  Load the ticker/exchange mapping for initial company discovery.
2.  Normalize CIK to a 10-character string; preserve the normalized CIK
    as the canonical SEC identifier.
3.  Fetch submissions and company facts for selected companies.
4.  Parse recent filings and facts.
5.  Validate required fields, timestamps, units, form types, and
    accession numbers.
6.  Upsert company and filing rows using stable unique keys.
7.  Upsert normalized facts without deleting older observations.
8.  Record ingestion and freshness events.
9.  Detect filings not previously seen and create notification events.
10. Dispatch notifications asynchronously or in a separate bounded
    delivery pass.
11. Record run status, counts, errors, and duration.

### 5.4 Initial coverage strategy

The SEC has a large issuer universe. The seven-day MVP must not try to
download every company and every fact at once.

-   Seed a modest list of companies for development and pilot use.
-   Add on-demand ingestion for a company after a valid lookup, subject
    to rate limits.
-   Poll submissions for watched companies on a configurable schedule.
-   Add broader coverage only after measuring request volume and
    database size.
-   Never claim complete coverage unless all required data has actually
    been ingested and validated.

### 5.5 Filing identity and timestamps

Use accession number as the primary filing identity in combination with
CIK. Store at least:

-   `cik`
-   `accession_number`
-   `form_type`
-   `filing_date`
-   `accepted_at` if provided by the source
-   `source_published_at` if explicitly available
-   `source_url`
-   `first_detected_at`
-   `processed_at`
-   `source_payload_hash`
-   `ingestion_run_id`

SEC submissions data commonly exposes filing dates and accession
numbers; a precise accepted timestamp may not be available for every
record in the bulk submissions payload. Do not infer a precise accepted
time from a date-only field. If the timestamp is not provided, return
`null` and expose a field-level availability or quality status.

------------------------------------------------------------------------

## 6. Normalized financial facts

### 6.1 Supported normalized concepts

Support the following canonical metrics where the source discloses a
mappable fact:

  --------------------------------------------------------------------------------------------------------
  Canonical metric        Typical XBRL concept candidates                          Notes
  ----------------------- -------------------------------------------------------- -----------------------
  `revenue`               `RevenueFromContractWithCustomerExcludingAssessedTax`,   Multiple candidates may
                          `Revenues`, `SalesRevenueNet`                            exist; document
                                                                                   precedence and avoid
                                                                                   double counting

  `operating_income`      `OperatingIncomeLoss`                                    Preserve reported units
                                                                                   and period

  `net_income`            `NetIncomeLoss`, with carefully defined candidate        Do not casually
                          handling                                                 substitute income
                                                                                   attributable to parent
                                                                                   or common shareholders

  `total_assets`          `Assets`                                                 Usually an
                                                                                   instant/balance-sheet
                                                                                   fact

  `operating_cash_flow`   `NetCashProvidedByUsedInOperatingActivities`             Use this canonical
                                                                                   label; do not call it
                                                                                   generic "cash flow"
                                                                                   without qualification
  --------------------------------------------------------------------------------------------------------

The exact concept set must be maintained in a versioned mapping
configuration. The table is a starting point, not an exhaustive
guarantee. SEC company facts typically exposes standard taxonomy facts;
custom company extensions may not appear in the standard company facts
endpoint.

### 6.2 Fact selection rules

Each normalized fact must preserve:

-   `metric`
-   `value`
-   `unit`
-   `currency` where applicable
-   `period_start` where applicable
-   `period_end`
-   `period_type` (`instant` or `duration`)
-   `fiscal_year` and `fiscal_period` when provided
-   `form_type`
-   `filed_date`
-   `accession_number`
-   `source_tag`
-   `source_url`
-   `mapping_version`
-   `quality_status`
-   `first_detected_at`
-   `processed_at`

Rules:

1.  Never convert absent data to `0`.
2.  Do not combine facts with incompatible units.
3.  Preserve original source values and units; normalization may add a
    canonical value but must not erase source representation.
4.  For duration metrics (revenue, operating income, net income,
    operating cash flow), return period start/end. For total assets,
    return instant period end and `period_type=instant`.
5.  For a requested annual view, prefer an annual filing fact (`10-K` or
    equivalent) and a full fiscal-year duration. For quarterly view,
    prefer the relevant quarterly duration from `10-Q` or equivalent. Do
    not assume every XBRL record's duration maps cleanly to a quarter.
6.  When facts are restated or repeated, keep the original fact
    observations. API responses may default to the most recently filed
    eligible fact for the same metric and period, but must expose the
    selected accession, filing date, and revision information.
7.  If more than one candidate tag exists, apply a documented
    deterministic precedence rule and mark low-confidence mappings where
    ambiguity remains.
8.  Avoid double-counting YTD facts as standalone quarter facts. Derive
    a quarter by subtraction only if the calculation is explicitly
    implemented, both periods are compatible, and the response marks
    `derived=true` and includes the source observations.
9.  XBRL values can be negative. Preserve sign.
10. Do not claim facts are audited, verified, or complete unless that
    status is directly supported.

### 6.3 Data quality statuses

Use a controlled set, e.g.:

-   `ok`: required fields present and mapping unambiguous.
-   `partial`: one or more optional fields/timestamps unavailable.
-   `ambiguous_mapping`: multiple plausible concepts or mapping
    uncertainty.
-   `invalid_source_value`: source value cannot be parsed safely.
-   `stale`: upstream source has not been refreshed within the
    configured threshold.
-   `unavailable`: source endpoint or requested fact unavailable.
-   `derived`: value calculated from other disclosed observations, with
    derivation metadata.

Do not let one company-level quality label conceal fact-level problems.
Return quality status at the relevant record level.

------------------------------------------------------------------------

## 7. Database model

Use UUID primary keys internally. Add migrations for all schema changes.
Store timestamps in UTC (`TIMESTAMPTZ`).

### 7.1 `companies`

-   `id UUID PRIMARY KEY`
-   `cik VARCHAR(10) NOT NULL UNIQUE`
-   `legal_name TEXT NOT NULL`
-   `ticker TEXT NULL`
-   `exchange TEXT NULL`
-   `sic_code TEXT NULL`
-   `sic_description TEXT NULL`
-   `entity_type TEXT NULL`
-   `source_url TEXT NOT NULL`
-   `source_updated_at TIMESTAMPTZ NULL`
-   `first_detected_at TIMESTAMPTZ NOT NULL`
-   `last_processed_at TIMESTAMPTZ NULL`
-   `created_at TIMESTAMPTZ NOT NULL`
-   `updated_at TIMESTAMPTZ NOT NULL`

A company may have multiple tickers over time. For MVP, keep the current
ticker/exchange on the company row and design a later-compatible
`company_ticker_history` table if needed. Do not treat ticker as a
permanent identity.

### 7.2 `filings`

-   `id UUID PRIMARY KEY`
-   `cik VARCHAR(10) NOT NULL REFERENCES companies(cik)`
-   `accession_number VARCHAR(25) NOT NULL`
-   `form_type TEXT NOT NULL`
-   `filing_date DATE NULL`
-   `accepted_at TIMESTAMPTZ NULL`
-   `source_published_at TIMESTAMPTZ NULL`
-   `source_url TEXT NOT NULL`
-   `source_payload_hash TEXT NULL`
-   `first_detected_at TIMESTAMPTZ NOT NULL`
-   `processed_at TIMESTAMPTZ NULL`
-   `ingestion_run_id UUID NULL`
-   `quality_status TEXT NOT NULL`
-   `created_at TIMESTAMPTZ NOT NULL`
-   Unique constraint: `(cik, accession_number)`

### 7.3 `financial_facts`

-   `id UUID PRIMARY KEY`
-   `cik VARCHAR(10) NOT NULL REFERENCES companies(cik)`
-   `metric TEXT NOT NULL`
-   `value NUMERIC NULL`
-   `unit TEXT NOT NULL`
-   `currency TEXT NULL`
-   `period_start DATE NULL`
-   `period_end DATE NOT NULL`
-   `period_type TEXT NOT NULL`
-   `fiscal_year INTEGER NULL`
-   `fiscal_period TEXT NULL`
-   `form_type TEXT NULL`
-   `filed_date DATE NULL`
-   `accession_number VARCHAR(25) NULL`
-   `source_tag TEXT NOT NULL`
-   `source_url TEXT NOT NULL`
-   `mapping_version TEXT NOT NULL`
-   `quality_status TEXT NOT NULL`
-   `derived BOOLEAN NOT NULL DEFAULT FALSE`
-   `source_payload_hash TEXT NULL`
-   `first_detected_at TIMESTAMPTZ NOT NULL`
-   `processed_at TIMESTAMPTZ NOT NULL`
-   `created_at TIMESTAMPTZ NOT NULL`
-   Unique key should prevent duplicate ingestion of the same source
    observation; choose a key that includes CIK, metric/source tag,
    unit, period, accession, and relevant dimensions where available.

### 7.4 `ingestion_runs`

-   `id UUID PRIMARY KEY`
-   `source TEXT NOT NULL`
-   `started_at TIMESTAMPTZ NOT NULL`
-   `finished_at TIMESTAMPTZ NULL`
-   `status TEXT NOT NULL`
-   `companies_seen INTEGER NOT NULL DEFAULT 0`
-   `filings_seen INTEGER NOT NULL DEFAULT 0`
-   `facts_seen INTEGER NOT NULL DEFAULT 0`
-   `inserted_count INTEGER NOT NULL DEFAULT 0`
-   `updated_count INTEGER NOT NULL DEFAULT 0`
-   `error_count INTEGER NOT NULL DEFAULT 0`
-   `error_summary TEXT NULL`
-   `created_at TIMESTAMPTZ NOT NULL`

### 7.5 `api_keys`

-   `id UUID PRIMARY KEY`
-   `owner_email TEXT NOT NULL`
-   `key_prefix TEXT NOT NULL`
-   `key_hash TEXT NOT NULL UNIQUE`
-   `plan TEXT NOT NULL DEFAULT 'free'`
-   `is_active BOOLEAN NOT NULL DEFAULT TRUE`
-   `created_at TIMESTAMPTZ NOT NULL`
-   `last_used_at TIMESTAMPTZ NULL`
-   `revoked_at TIMESTAMPTZ NULL`

Store only a secure hash of the API key, never the raw key. Show the raw
key once at creation. Use a cryptographically secure random generator;
key material should have enough entropy (at least 32 random bytes). Use
a constant-time comparison when verifying a hash if the chosen method
requires direct comparison.

### 7.6 `api_usage`

-   `id BIGSERIAL PRIMARY KEY`
-   `api_key_id UUID NOT NULL REFERENCES api_keys(id)`
-   `request_id TEXT NOT NULL`
-   `route_template TEXT NOT NULL`
-   `http_status INTEGER NOT NULL`
-   `units INTEGER NOT NULL DEFAULT 1`
-   `response_bytes BIGINT NULL`
-   `occurred_at TIMESTAMPTZ NOT NULL`

Add indexes for `(api_key_id, occurred_at)` and `request_id`. Do not log
query strings containing secrets or raw payloads unnecessarily.

### 7.7 `company_watches`

-   `id UUID PRIMARY KEY`
-   `api_key_id UUID NOT NULL REFERENCES api_keys(id)`
-   `cik VARCHAR(10) NOT NULL REFERENCES companies(cik)`
-   `destination_type TEXT NOT NULL` (`webhook` or `email`)
-   `destination TEXT NOT NULL`
-   `secret_hash TEXT NULL` (if signing webhook payloads, store a
    suitable secret securely; never return it later)
-   `is_active BOOLEAN NOT NULL DEFAULT TRUE`
-   `created_at TIMESTAMPTZ NOT NULL`
-   `last_delivered_at TIMESTAMPTZ NULL`

Validate email addresses and webhook URLs. Reject localhost, link-local,
private, and metadata-service IP targets for webhooks to mitigate SSRF.
Revalidate resolved IPs at delivery time and block redirects to
disallowed destinations.

### 7.8 `notification_deliveries`

-   `id UUID PRIMARY KEY`
-   `watch_id UUID NOT NULL REFERENCES company_watches(id)`
-   `filing_id UUID NOT NULL REFERENCES filings(id)`
-   `event_id TEXT NOT NULL UNIQUE`
-   `status TEXT NOT NULL` (`pending`, `delivered`, `retrying`,
    `failed`)
-   `attempt_count INTEGER NOT NULL DEFAULT 0`
-   `last_status_code INTEGER NULL`
-   `last_error_redacted TEXT NULL`
-   `next_attempt_at TIMESTAMPTZ NULL`
-   `created_at TIMESTAMPTZ NOT NULL`
-   `delivered_at TIMESTAMPTZ NULL`

### 7.9 Indexes and retention

-   Index filings on `(cik, filing_date DESC)` and
    `(cik, first_detected_at DESC)`.
-   Index facts on `(cik, metric, period_end DESC)`.
-   Index company name using PostgreSQL trigram or normalized prefix
    search only if extension availability is confirmed; otherwise use
    `ILIKE` with a sensible limit.
-   Index notification delivery status and `next_attempt_at`.
-   Index usage by API key and time.
-   Define a documented retention policy for request logs, delivery
    payloads, and exports. Avoid retaining more customer data than
    necessary.

------------------------------------------------------------------------

## 8. API contract

All endpoints use JSON except CSV export. Prefix all public endpoints
with `/v1`. Require `X-API-Key: <key>` for customer endpoints. Health
endpoints may be unauthenticated but must not disclose internal
infrastructure details.

### 8.1 Standard response conventions

-   JSON timestamps use ISO 8601 UTC, e.g. `2026-10-17T12:30:00Z`.
-   Dates without a time remain ISO dates (`YYYY-MM-DD`).
-   Money-like financial facts are returned as numeric values with
    explicit unit/currency; never assume USD without source evidence.
-   List endpoints return pagination metadata: `limit`, `next_cursor` or
    `next_offset`, and `has_more`.
-   Return a stable error envelope:

``` json
{
  "error": {
    "code": "invalid_parameter",
    "message": "The requested limit is outside the permitted range.",
    "request_id": "req_..."
  }
}
```

Do not expose stack traces, SQL, secrets, or raw upstream error bodies.

### 8.2 Company lookup

`GET /v1/companies/search?q={query}&limit=10`

-   `q` required; match ticker, CIK, or company name.
-   `limit` defaults to 10; allowed 1--50.
-   CIK search should accept values with or without leading zeroes and
    normalize to 10 digits.
-   Ticker matching should be case-insensitive.
-   Return relevance-ranked matches, but do not claim a fuzzy match is
    definitive.

Example:

``` json
{
  "data": [
    {
      "cik": "0000320193",
      "legal_name": "Apple Inc.",
      "ticker": "AAPL",
      "exchange": "Nasdaq",
      "source_url": "https://www.sec.gov/Archives/edgar/data/320193/...",
      "first_detected_at": "2026-10-17T12:00:00Z",
      "last_processed_at": "2026-10-17T12:01:00Z",
      "quality_status": "ok"
    }
  ],
  "meta": {"limit": 10, "has_more": false}
}
```

`GET /v1/companies/{cik}` returns the canonical company profile and
source metadata. A valid CIK with no cached record may trigger on-demand
ingestion, but the API should return a clear processing status or
`202 Accepted` rather than blocking for a long upstream request.

### 8.3 Recent filings

`GET /v1/companies/{cik}/filings?limit=20&form_type=10-K`

-   `limit` defaults to 20; allowed 1--100.
-   Optional `form_type` filter.
-   Optional `since` ISO date filter.
-   Sort newest filing date first, with stable tie-breaking by accession
    number.
-   Return accepted/published timestamps as `null` if not provided by
    source.

Example:

``` json
{
  "data": [
    {
      "cik": "0000320193",
      "accession_number": "0000320193-26-000001",
      "form_type": "10-Q",
      "filing_date": "2026-10-17",
      "accepted_at": null,
      "source_published_at": null,
      "source_url": "https://www.sec.gov/Archives/edgar/data/320193/...",
      "first_detected_at": "2026-10-17T12:05:00Z",
      "processed_at": "2026-10-17T12:05:02Z",
      "quality_status": "partial"
    }
  ],
  "meta": {"limit": 20, "has_more": false}
}
```

The example values are illustrative. Never seed production with
fabricated sample facts or claim the example timestamps are actual SEC
values.

### 8.4 Financial facts

`GET /v1/companies/{cik}/facts?metric=revenue&period=annual&limit=20`

Supported `metric` values: - `revenue` - `operating_income` -
`net_income` - `total_assets` - `operating_cash_flow`

Supported `period`: `annual`, `quarterly`, or `all`. Default to
`annual`. `limit` defaults to 20; allowed 1--100.

Optional filters: - `from` date - `to` date - `form_type` -
`include_derived` boolean, default `false`

Example:

``` json
{
  "data": [
    {
      "metric": "revenue",
      "value": 391035000000,
      "unit": "USD",
      "currency": "USD",
      "period_start": "2025-09-28",
      "period_end": "2026-09-26",
      "period_type": "duration",
      "fiscal_year": 2026,
      "fiscal_period": "FY",
      "form_type": "10-K",
      "filed_date": "2026-10-17",
      "accession_number": "0000000000-26-000000",
      "source_tag": "RevenueFromContractWithCustomerExcludingAssessedTax",
      "source_url": "https://www.sec.gov/Archives/edgar/data/...",
      "mapping_version": "1.0.0",
      "quality_status": "ok",
      "derived": false,
      "first_detected_at": "2026-10-17T12:05:00Z",
      "processed_at": "2026-10-17T12:05:02Z"
    }
  ],
  "meta": {"limit": 20, "has_more": false}
}
```

The example is schema-only and contains placeholder dates/identifiers;
do not use its values as real financial data.

### 8.5 Freshness endpoint

`GET /v1/companies/{cik}/freshness`

Return: - latest successful source fetch time, - most recent filing
source date/time available, - first detection and processing times for
the latest filing, - `latency_seconds` only when both comparable
timestamps exist, - latest ingestion status and errors in redacted
form, - age of last successful refresh, - quality summary.

Do not compare date-only filing dates with precise timestamps and call
the difference source latency. Distinguish `source_date_age_seconds`
from `publication_to_detection_seconds` and only compute the latter when
a precise source timestamp exists.

Example:

``` json
{
  "cik": "0000320193",
  "last_successful_fetch_at": "2026-10-17T12:00:00Z",
  "latest_filing": {
    "source_published_at": null,
    "first_detected_at": "2026-10-17T12:05:00Z",
    "processed_at": "2026-10-17T12:05:02Z",
    "publication_to_detection_seconds": null,
    "processing_seconds": 2.0
  },
  "status": "partial",
  "notes": ["The SEC source did not provide a precise publication timestamp for this record."]
}
```

### 8.6 Company watches and notifications

`POST /v1/watches`

Request:

``` json
{
  "cik": "0000320193",
  "destination_type": "webhook",
  "destination": "https://customer.example.com/sec-events"
}
```

Return a watch ID and active status. Email destinations are also
supported. Do not return webhook secrets after creation.

`GET /v1/watches` lists watches for the authenticated API key.

`DELETE /v1/watches/{watch_id}` deactivates a watch. Deletion should
stop future deliveries but should not rewrite historical delivery
records.

Webhook payload:

``` json
{
  "event_id": "evt_<unique-id>",
  "event_type": "sec.filing.detected",
  "created_at": "2026-10-17T12:05:02Z",
  "data": {
    "cik": "0000320193",
    "accession_number": "0000320193-26-000001",
    "form_type": "10-Q",
    "filing_date": "2026-10-17",
    "source_url": "https://www.sec.gov/Archives/edgar/data/..."
  }
}
```

-   Sign webhook requests using HMAC-SHA256 with a per-watch secret.
    Include timestamp and signature headers, and document verification
    code.
-   Retry network failures, `408`, `429`, and `5xx` using exponential
    backoff with jitter; stop after a configurable finite attempt count.
-   Do not retry ordinary `4xx`.
-   Use stable event IDs to make deliveries idempotent.
-   Set short connection/read timeouts.
-   Prevent SSRF and redirect-based SSRF. Block private/reserved IPs,
    localhost, link-local, and cloud metadata endpoints; re-resolve DNS
    at delivery.
-   Email delivery is optional in the seven-day MVP if credentials or
    deliverability setup are unavailable; webhook delivery is the
    required working path. If email is exposed, clearly report
    configuration status and delivery errors.

### 8.7 Developer onboarding and API keys

`POST /v1/developer/api-keys` creates an API key for an authenticated
owner or a simple email-verified onboarding flow.

For the MVP, if full email verification cannot be completed in seven
days, issue a single development key through a protected admin script
and document the limitation. Never expose an unrestricted public
key-creation endpoint without abuse controls.

`GET /v1/developer/usage?from=...&to=...` returns: - total requests, -
successful requests, - errors, - requests by route, - export
rows/bytes, - current plan limit and usage.

`DELETE /v1/developer/api-keys/{key_id}` revokes a key.

-   Hash API keys at rest.
-   Show a new key only once.
-   Support immediate revocation.
-   Apply per-key rate limits and plan quotas.
-   Record usage after authentication and route resolution.
-   Meter exports by rows/bytes in addition to the request count.
-   Return `429 Too Many Requests` with `Retry-After` when limits are
    exceeded.
-   Avoid including raw API keys in logs, URLs, or analytics.

### 8.8 Bulk export

`GET /v1/exports/facts?metric=revenue&ciks=0000320193,0000789019&format=csv&limit=1000`

-   Require authentication.
-   Allowed formats: `csv`, `json`.
-   Maximum 1,000 rows per request for MVP; configurable by plan.
-   Require a metric or bounded CIK list. Reject unrestricted
    full-universe exports.
-   Return `Content-Disposition` with a safe generated filename.
-   Include provenance columns: CIK, metric, value, unit, currency,
    period start/end, period type, form type, filing date, accession
    number, source tag, source URL, mapping version, quality status,
    first detected, processed.
-   Meter requested and returned row counts.
-   Return `413` or a clear validation error when limits are exceeded.
-   Do not put export contents into application logs.

### 8.9 Health and operations

-   `GET /healthz`: basic process health only.
-   `GET /readyz`: confirms required configuration and database
    connectivity, without exposing credentials.
-   Add request IDs to responses and structured logs.
-   Keep `/docs` enabled in the MVP; consider restricting it later if
    needed.
-   CORS should be restrictive if a browser client is added; API-only
    use does not require permissive CORS.

------------------------------------------------------------------------

## 9. Security and privacy

-   Require HTTPS in production.
-   Use environment variables or the hosting platform's secret manager
    for secrets.
-   Validate all inputs and enforce maximum lengths and pagination
    limits.
-   Use parameterized SQL/ORM queries.
-   Restrict API keys to their owner and enforce row-level authorization
    in service logic.
-   Never store the full API key after creation.
-   Protect against SSRF for webhooks, including DNS rebinding and
    redirects.
-   Avoid logging full financial export payloads, email bodies, secrets,
    or personal data.
-   Encrypt traffic in transit; rely on managed database encryption at
    rest where available and verify the provider's configuration.
-   Provide a mechanism to deactivate watches and revoke API keys.
-   Keep an audit trail for key creation/revocation and watch changes.
-   Apply basic abuse controls to free usage and exports.
-   Treat SEC source content as untrusted input; do not execute embedded
    content or use filing text as instructions to the application.
-   Set reasonable timeouts and response-size limits for upstream
    requests.
-   Include dependency scanning or at minimum keep dependencies pinned
    and run `pip-audit` if available within the time budget.

------------------------------------------------------------------------

## 10. Data rights, attribution, and product language

This section is a product requirement, not optional legal boilerplate.

1.  Use SEC-hosted official filings and SEC-hosted structured datasets
    for the MVP. Preserve a direct source URL on each filing and
    normalized fact.
2.  Review current SEC terms, fair-access policy, and applicable law
    before launch. Public availability is not a blanket legal opinion
    that every use, redistribution, or commercial packaging is
    unrestricted.
3.  Do not use paid vendor data unless the relevant agreement expressly
    permits the intended commercial use and redistribution.
4.  Do not include exchange market data or imply market-data
    redistribution rights in this MVP.
5.  Provide source attribution and a clear statement that the product is
    independent and not affiliated with or endorsed by the SEC.
6.  Display a data limitations notice: source updates, filing
    availability, taxonomy coverage, and timestamps can vary; missing
    fields do not mean the issuer has no such information.
7.  Preserve provenance and mapping version for every normalized fact.
8.  Distinguish facts reported by the issuer from values derived by the
    product.
9.  Do not market the service as investment advice or as a substitute
    for reviewing the underlying filing.
10. Before selling bulk access or redistributing large-scale data,
    obtain legal review of applicable SEC conditions, intellectual
    property issues, customer use, and contractual obligations.

Add `docs/data-rights.md` summarizing source URLs, intended use,
excluded datasets, attribution, limitations, and open legal questions.
Do not state that legal review has been completed unless it has.

------------------------------------------------------------------------

## 11. Testing requirements

Use deterministic local fixtures for tests. Unit tests must not call the
SEC or third-party services. Live SEC smoke tests should be optional and
explicitly enabled by an environment variable.

### 11.1 Unit tests

-   CIK normalization: leading zeros, no leading zeros, invalid strings.
-   Ticker normalization: case-insensitive search and ambiguous ticker
    handling.
-   Company name search: exact/prefix matches and bounded results.
-   SEC response parsing: missing optional fields, malformed payload,
    empty submissions.
-   Filing deduplication: repeated ingestion does not create duplicate
    accession records.
-   Timestamp handling: missing accepted timestamp stays null; timezone
    normalization works.
-   Fact normalization: metric mapping, units, periods, signs, missing
    facts, competing candidate tags.
-   Annual/quarterly classification: prevent YTD duration from being
    misrepresented as a standalone quarter.
-   Restatements/amendments: original fact observations remain
    accessible.
-   Quality statuses: ambiguous mapping, partial metadata, stale
    sources.
-   API key generation, hashing, verification, and revocation.
-   Usage metering: successful requests, failed requests, export row
    counts, and quota enforcement.
-   Export escaping: commas, quotes, newlines, UTF-8, null values.
-   Webhook signature generation and verification.
-   Retry policy and finite max attempts.
-   SSRF validation: localhost, private IPv4/IPv6, link-local, metadata
    endpoints, redirects, DNS changes.
-   Stable event ID and idempotent delivery creation.

### 11.2 API integration tests

-   Company lookup by ticker, CIK, and name.
-   Company not found returns the documented status and error envelope.
-   Recent filings are sorted and filtered correctly.
-   Facts endpoint returns canonical metrics with source provenance.
-   Freshness endpoint does not calculate invalid latency from date-only
    timestamps.
-   Watch creation/listing/deactivation is scoped to the caller.
-   New filing creates one notification per matching active watch.
-   Webhook delivery status updates correctly after success/failure.
-   API key revocation immediately blocks access.
-   Usage endpoint reports correct totals.
-   CSV and JSON exports respect row limits and include required
    provenance.
-   `/openapi.json` includes all public endpoints, schemas, auth
    requirements, and response codes.

### 11.3 Live smoke tests

Only run when `SEC_LIVE_TESTS=1` and a valid descriptive SEC
`User-Agent` is configured.

-   Fetch one known company submissions JSON.
-   Fetch one known company facts JSON.
-   Validate response shape, HTTP status, and source URL.
-   Never use live data as the only test fixture.
-   Do not run load tests against SEC endpoints.

### 11.4 Definition of done

-   All automated tests pass.
-   Lint/format checks pass.
-   Database migrations apply from an empty database.
-   A fresh developer can start the service using README instructions.
-   The API can ingest at least one company, query filings/facts, return
    freshness metadata, and export a bounded result.
-   A test webhook receives a signed filing event and verifies its
    signature.
-   API key creation/revocation and usage metering work.
-   No secret is committed to source control.
-   OpenAPI is available and sample code succeeds against the deployed
    API.
-   Data rights and limitations are documented.

------------------------------------------------------------------------

## 12. Observability and quality targets

Track the following internal metrics from day one:

-   SEC requests by endpoint and status.
-   SEC response latency and retry counts.
-   Successful/failed ingestion runs.
-   Companies, filings, and facts inserted/updated.
-   Duplicate filing rate.
-   Percentage of facts with source URL, source tag, unit, period, and
    mapping version.
-   Number of facts marked `partial` or `ambiguous_mapping`.
-   Source-to-detection latency only where comparable source timestamps
    exist.
-   Detection-to-processing duration.
-   Webhook delivery success rate, retry count, and age of oldest
    pending delivery.
-   API latency, error rate, requests per API key, export rows/bytes.
-   Database size and scheduled job duration.

### Initial acceptance targets (provisional)

-   Zero duplicate filing rows for repeated ingestion of the same source
    payload.
-   100% of returned normalized facts include source URL, source tag,
    unit, period end, and mapping version, or are excluded with a
    documented reason.
-   At least 95% of valid API requests complete successfully in local
    integration tests, excluding deliberately injected upstream
    failures.
-   At least 95% of test webhook events are delivered within the
    configured retry window in controlled tests.
-   Every unavailable precise source timestamp is represented as `null`,
    not inferred.
-   For the pilot watch list, polling interval and observed freshness
    are documented; no fixed public latency SLA until measured.

These are MVP engineering targets, not claims about production
performance or SEC availability.

------------------------------------------------------------------------

## 13. Seven-day implementation plan

### Day 1 --- Repository, schema, and source client

-   Initialize FastAPI, settings, database connection, migrations, and
    structured logging.
-   Implement SEC HTTP client with descriptive User-Agent, timeouts,
    caching, rate limiting, and retry handling.
-   Add fixture payloads for company submissions and company facts.
-   Deliverable: app boots and can parse a fixture.

### Day 2 --- Company and filing ingestion

-   Implement CIK normalization, ticker mapping import, submissions
    parsing, filing upsert, and ingestion-run tracking.
-   Add idempotency tests.
-   Deliverable: ingest one selected company and query its filings from
    the database.

### Day 3 --- Financial fact normalization

-   Implement the five canonical metrics and a versioned concept
    mapping.
-   Preserve source tag, unit, fiscal period, accession, source URL,
    timestamps, and quality status.
-   Add tests for duration/instant, missing values, negative values, and
    restatements.
-   Deliverable: normalized fact API data in the database.

### Day 4 --- Public API and OpenAPI

-   Implement company search, company profile, filings, facts, and
    freshness endpoints.
-   Add pagination, validation, request IDs, and standard error
    responses.
-   Deliverable: documented API works end to end.

### Day 5 --- Keys, usage, notifications

-   Implement secure API keys, quotas, usage logging, watches, webhook
    signing, delivery records, and retry handling.
-   Email is optional if setup threatens the schedule; webhook is
    mandatory.
-   Deliverable: test key calls API and a test webhook receives a filing
    event.

### Day 6 --- Bulk export, docs, and deployment

-   Implement bounded CSV/JSON export and usage metering.
-   Write README, data dictionary, data rights, sample Python/cURL,
    `.env.example`, and deployment instructions.
-   Deploy API and scheduler; verify migrations and secrets.
-   Deliverable: a developer can onboard without direct help.

### Day 7 --- End-to-end validation and pilot

-   Run the full test suite and optional SEC smoke test.
-   Verify provenance, timestamp correctness, duplicate handling,
    notification idempotency, rate limiting, and export caps.
-   Create a sample customer walkthrough and contact pilot prospects.
-   Deliverable: stable demo, documented limitations, and a list of
    issues prioritized by severity.

### Scope-cut order if behind schedule

1.  Keep company lookup, filings, normalized facts, provenance, and
    freshness.
2.  Keep API keys, basic usage metering, and bounded export.
3.  Keep webhook notifications with signed delivery and retries.
4.  Defer email notifications, advanced fuzzy search, elaborate UI, and
    complex billing.
5.  Never cut source attribution, timestamp honesty, authentication,
    export limits, or data-rights safeguards.

------------------------------------------------------------------------

## 14. Deployment and operations

### Required environment variables

``` bash
APP_ENV=development
APP_NAME=PublicCompanyDataAPI
APP_VERSION=0.1.0
DATABASE_URL=postgresql+psycopg://user:password@localhost:5432/companydata
SEC_USER_AGENT="PublicCompanyDataAPI/0.1.0 contact=ops@example.com"
SEC_MIN_REQUEST_INTERVAL_SECONDS=0.25
SEC_TIMEOUT_SECONDS=20
SEC_MAX_RETRIES=5
INGESTION_POLL_INTERVAL_SECONDS=300
API_KEY_PEPPER=replace-with-random-secret
WEBHOOK_SIGNING_SECRET=replace-with-random-secret
MAX_EXPORT_ROWS=1000
DEFAULT_RATE_LIMIT_PER_MINUTE=60
SEC_LIVE_TESTS=0
```

-   `.env.example` must contain placeholders only.
-   Generate strong random secrets for every deployment.
-   Do not use example credentials in production.
-   If a pepper is used in API key hashing, losing it will invalidate
    keys; document rotation and recovery.
-   Use the hosting platform's secret manager where available.

### Local development

Provide Docker Compose for PostgreSQL and the API, or document a local
PostgreSQL setup. Include commands for:

-   installing dependencies,
-   applying migrations,
-   running tests,
-   creating a development API key,
-   ingesting one sample CIK,
-   starting the API,
-   running the SEC poll job,
-   running a test webhook receiver.

### Production topology

Use one API service, one scheduled ingestion job, and one PostgreSQL
database. For a small pilot, a single deployment with separate API and
job commands is acceptable if the scheduler cannot run duplicate
concurrent jobs. Use a database advisory lock or equivalent single-run
guard.

-   HTTPS only.
-   Automated database backups if supported by the chosen plan; test
    restore instructions.
-   Keep staging and production credentials separate.
-   Set resource limits and a bounded worker count.
-   Add a deployment health check.
-   Pin dependencies and apply security updates.
-   Configure alerts for repeated ingestion failures, stale watched
    companies, and webhook delivery backlog.
-   Do not store bulk exports indefinitely; use temporary files or
    streamed responses and document expiration.

------------------------------------------------------------------------

## 15. Budget guardrails

Target initial cash expenditure below ₹25,000 INR. The build assumes the
founder writes the code and does not include salary or the value of
founder time.

  Item                                         Planned cap
  ------------------------------------------ -------------
  Domain and basic landing page                     ₹1,500
  Hosting and database for prototype/pilot          ₹4,000
  Email/testing/monitoring allowance                ₹1,500
  Outreach and demo expenses                        ₹3,000
  Contingency                                       ₹5,000
  **Planned total cap**                        **₹15,000**
  **Remaining buffer under ₹25,000**           **₹10,000**

These are planning allowances, not vendor quotes. Check current prices,
taxes, free-tier limits, and commercial-use terms before purchasing. Do
not buy paid market data for the MVP. Do not incur recurring paid
infrastructure until a pilot customer or measured workload justifies it.

------------------------------------------------------------------------

## 16. Pilot validation and go/no-go criteria

### Within the first 30 days

-   Interview at least 15 developers, fintech builders, research teams,
    or data product owners.
-   Get at least 5 qualified prospects to test the API with a realistic
    use case.
-   Obtain 3 explicit willingness-to-pay signals at a proposed price.
-   Close at least 2 paid pilots or one paid pilot with a clear
    follow-on commitment.
-   Demonstrate that filing detection, normalization, provenance, and
    freshness work for the pilot watch list.
-   Record data-quality issues and latency distributions rather than
    making unsupported marketing claims.

### Go

Continue if customers pay for the combination of normalized facts,
source provenance, update monitoring, and developer convenience.

### Iterate

If users like the API but won't pay, identify whether the missing value
is coverage, historical depth, exportability, latency, or integration
support. Test one change at a time.

### Stop or reposition

If 15 qualified interviews and 5 hands-on trials produce no credible
willingness to pay, do not expand coverage or purchase market-data
feeds. Revisit the buyer and the specific data problem.

------------------------------------------------------------------------

## 17. Final acceptance checklist

Before calling the MVP complete, confirm all of the following:

-   [ ] Company lookup supports ticker, CIK, and company name.
-   [ ] Recent filings return form type, filing date, accepted/published
    timestamps when available, and source URL.
-   [ ] Financial facts support revenue, operating income, net income,
    total assets, and operating cash flow where disclosed.
-   [ ] Facts preserve units, periods, source tags, accession/source
    references, and mapping version.
-   [ ] First-detected and processed timestamps are recorded.
-   [ ] Missing precise source timestamps remain null.
-   [ ] Repeated ingestion is idempotent.
-   [ ] New filing events can trigger a signed webhook.
-   [ ] Email notification is implemented only if safely configured;
    otherwise its limitation is documented.
-   [ ] API keys are hashed at rest, revocable, and never logged.
-   [ ] API usage and export usage are metered.
-   [ ] CSV and JSON exports enforce row limits and include provenance.
-   [ ] OpenAPI and sample cURL/Python code are available.
-   [ ] Automated tests pass and are documented.
-   [ ] SEC rate-limit handling, source attribution, data-rights
    limitations, and non-affiliation disclaimer are documented.
-   [ ] Deployment, migration, backup, and recovery instructions exist.
-   [ ] No paid vendor data is redistributed without explicit rights.

**Build principle:** correctness and provenance are the product. A
smaller dataset with honest timestamps, stable identifiers, and
reproducible financial facts is more valuable than a broad dataset with
uncertain mappings or misleading freshness claims.
