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
| Company profile, on-demand ingestion (`202`) | `GET /v1/companies/{cik}` |
| Recent filings with SEC source links and honest timestamps | `GET /v1/companies/{cik}/filings` |
| Normalized facts: revenue, operating income, net income, total assets, operating cash flow | `GET /v1/companies/{cik}/facts` |
| Freshness: fetch age, detection/processing times, status | `GET /v1/companies/{cik}/freshness` |
| Watches and signed webhook deliveries | `POST/GET/DELETE /v1/watches`, `GET /v1/watches/{id}/deliveries` |
| API keys and usage | `POST/GET/DELETE /v1/developer/api-keys`, `GET /v1/developer/usage` |
| Bounded CSV/JSON export with provenance | `GET /v1/exports/facts` |
| Public coverage stats, cached 30 s, no key | `GET /v1/stats` |
| Health | `GET /healthz`, `GET /readyz` |
| Marketing site POC with pilot pricing, `llms.txt` for agents | `GET /`, `GET /llms.txt` (static files in `site/`) |
| Universe: seed CIKs, budgeted resumable bulk ingestion with backoff | `scripts/bulk_ingest.py`, poller refreshes due members |

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

docker compose up -d db                 # PostgreSQL on localhost:5432
alembic upgrade head                    # apply migrations

python scripts/create_api_key.py you@example.com --plan pilot   # prints the key once
python scripts/import_tickers.py        # optional: seed ~10k company identities from the SEC ticker file
python scripts/ingest_company.py 320193 # ingest one company (filings + facts) from the SEC

# bulk coverage: define a universe, then ingest it within an SEC request budget (resumable)
python scripts/bulk_ingest.py --seed-file data/universe.sample.txt --seed-only
python scripts/bulk_ingest.py --seed-tickers --top 500 --seed-only   # or the first 500 issuers of the SEC ticker file
python scripts/bulk_ingest.py --budget 400 --history-pages 1          # one pass; re-run until --status shows due_now 0
python scripts/bulk_ingest.py --status

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
  "mapping_version": "1.0.0", "quality_status": "ok", "derived": false,
  "revision_count": 1, "first_detected_at": "2026-10-17T12:05:00Z", "processed_at": "2026-10-17T12:05:02Z"
}
```

Errors always use `{"error": {"code", "message", "request_id"}}`; every response carries
`X-Request-ID`. Rate limits return `429` with `Retry-After`.

### Facts semantics worth knowing

- `period=annual|quarterly|all` filters on `period_class`, which is computed from the reported
  period dates. A 6- or 9-month year-to-date value is `ytd`, never a quarter, even though the
  SEC labels it `fp=Q2/Q3`.
- Default view returns one observation per period (latest filed, preferred tag) with
  `revision_count`. `include_all_observations=true` returns restatements and alternate tags.
- `include_derived=true` adds standalone quarters computed as `YTD(n) - YTD(n-1)` with
  `derived=true`, `quality_status=derived` and the two source observations in `derivation`.
- Absent facts are absent. Unparseable values are `null` with `invalid_source_value`.

## Onboarding

Self-serve signup is not in the MVP. Keys are issued by an operator via
`scripts/create_api_key.py` or `POST /v1/developer/api-keys` protected by `X-Admin-Token`
(disabled unless `ADMIN_TOKEN` is set). Key holders can list and revoke keys that share their
owner email. Plans: `free` (60 req/min, 10k req/month, 5 watched companies), `builder` (300/min,
250k/month, 50 watches), `team` (1,000/min, 2M/month, 500 watches), `enterprise`, `internal`; all
capped at 1,000 export rows per request. Limits live in `PLAN_LIMITS` and match the pricing page.

## Deployment

See `docs/operations.md` for topology, secret rotation, backups, monitoring and retention.
`Dockerfile` serves the API; run the poller with the same image and
`python scripts/poll_sec.py`. `docker-compose.yml` runs db + migrate + api + poller locally.

## Documentation

- `docs/data-dictionary.md`: every column and status, the concept mapping and precedence rule.
- `docs/data-rights.md`: sources, attribution, exclusions, limitations notice, open legal questions.
- `docs/operations.md`: run book.
- `docs/implementation-checklist.md`: what was built, in priority order.

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
- Rate limiting is in-process; multiple API replicas multiply the effective limit.
- SSRF protection validates at creation and re-resolves DNS immediately before each delivery,
  but the HTTP client still connects by hostname, leaving a small rebinding window.
- Company search uses `LIKE` with a bounded scan; no trigram index yet.
- Usage/delivery retention purges are documented SQL, not automated.
- Coverage is limited to companies that have been ingested; nothing is "complete".

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
