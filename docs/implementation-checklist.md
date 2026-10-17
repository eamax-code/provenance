# Implementation checklist (MVP, priority order)

Derived from AGENTS.md. Each item is done only when its tests pass. Status as of 2026-10-17: all items below are implemented and tested, with the exceptions noted inline.

## 0. Foundation
- [x] pyproject (FastAPI, Pydantic v2, SQLAlchemy 2, Alembic, httpx, pytest, ruff), `.env.example`, `.gitignore`
- [x] Settings (pydantic-settings), structured logging with request IDs, error envelope
- [x] DB models for all 8 tables; Alembic initial migration; portable types (Postgres prod, SQLite tests)
- [x] SEC HTTP client: descriptive User-Agent, timeouts, rate limiter, ETag cache, backoff on 429/5xx, Retry-After

## 1. Vertical slice: company → filings → facts
- [x] CIK normalization; ticker/exchange mapping import; submissions parsing (recent + null-safe timestamps)
- [x] Idempotent company/filing upsert with first_detected_at preserved; ingestion_runs recorded
- [x] Versioned concept mapping (mapping_version 1.0.0) for 5 metrics; deterministic precedence; quality statuses
- [x] Annual/quarterly classification by duration; YTD never labeled as a quarter; derived facts only when explicit
- [x] Facts upsert keeps all observations (restatements), unique source-observation key

## 2. Public API + OpenAPI
- [x] `/v1/companies/search`, `/v1/companies/{cik}` (202 on-demand), `/filings`, `/facts`, `/freshness`
- [x] Pagination meta, validation, 404/422 envelopes, request IDs, `/healthz`, `/readyz`

## 3. Keys, usage, rate limits
- [x] API key: 32 random bytes, prefix + peppered SHA-256 hash, shown once, revocation, constant-time verify
- [x] Per-key rate limit (429 + Retry-After), usage rows per request, `/v1/developer/usage`, admin create-key script

## 4. Watches + webhooks
- [x] `POST/GET/DELETE /v1/watches` scoped to key; webhook URL SSRF validation (private/link-local/metadata/IPv6)
- [x] New filing → one delivery per active watch with stable event_id; HMAC-SHA256 signing; retries with jitter, finite
- [x] Delivery pass re-resolves DNS, blocks redirects; delivery status endpoint; email adapter implemented but not exercised against a real SMTP server

## 5. Bounded export
- [x] `/v1/exports/facts` CSV/JSON, max rows, metric or CIK list required, provenance columns, Content-Disposition, metered

## 6. Jobs, docs, deployment
- [x] `scripts/ingest_company.py`, `scripts/poll_sec.py` (advisory lock), `scripts/create_api_key.py`, test webhook receiver
- [x] README, data-dictionary, data-rights, operations docs, Dockerfile, docker-compose, sample cURL/Python
- [x] Optional `SEC_LIVE_TESTS=1` smoke test written (not executed: needs a real contact email); ruff clean; 141 tests green on SQLite and PostgreSQL 16; migrations verified on both
