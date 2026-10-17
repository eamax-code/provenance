# Operations

## Topology

One API process (`uvicorn app.main:app`), one poller (`python scripts/poll_sec.py`), one
PostgreSQL database. The poller takes a PostgreSQL advisory lock (`pg_try_advisory_lock`) so
duplicate concurrent runs skip themselves; cron with `--once` is also safe.

## Configuration

See `.env.example`. `GET /readyz` returns 503 with a list of configuration problems (never
secret values) when:

- `SEC_USER_AGENT` lacks `contact=`;
- `API_KEY_PEPPER` / `WEBHOOK_SIGNING_SECRET` are missing or shorter than 16 chars;
- production uses SQLite or allows private webhook destinations.

### Secret rotation

- **API_KEY_PEPPER**: the hash of every key depends on it. Rotating invalidates all keys; issue
  new keys after rotation. Back up the pepper in the platform secret manager.
- **WEBHOOK_SIGNING_SECRET**: per-watch secrets are derived from it. Rotating invalidates every
  customer's webhook secret; customers must recreate watches. Rotate only with notice.
- **ADMIN_TOKEN**: rotate freely; it only protects `POST /v1/developer/api-keys`.

## Deployment (small pilot)

1. Provision managed PostgreSQL (enable automated backups) and set `DATABASE_URL`.
2. Set all secrets via the platform secret manager; never commit `.env`.
3. Run `alembic upgrade head` as a release step (the Compose `migrate` service does this).
4. Start the API with 1-2 workers behind HTTPS; health check `GET /healthz`, readiness `GET /readyz`.
5. Run the poller as a separate process or a cron job: `python scripts/poll_sec.py --once` every
   `INGESTION_POLL_INTERVAL_SECONDS`.
6. Create the first API key: `python scripts/create_api_key.py you@example.com --plan pilot`.

The Dockerfile serves the API by default; override the command for the poller.

## Backups and recovery

- Use the managed database's automated snapshots. Test a restore into a scratch database:
  `pg_restore` / provider console, then `alembic current` should report the head revision.
- Everything except API keys, watches and usage can be rebuilt from the SEC by re-ingesting;
  the `.sec_cache` directory is disposable.
- After restore, re-run `alembic upgrade head` and `scripts/poll_sec.py --once`.

## Monitoring

Structured JSON logs (one line per event) include `request_id`, route template, status,
duration, SEC request status/retries/duration, ingestion counts, and webhook outcomes. Suggested
alerts for the pilot:

- `ingestion_runs.status = failed` twice in a row.
- Any watched company with `last_successful_fetch_at` older than 2 x poll interval.
- `notification_deliveries` with `status in (pending, retrying)` older than 1 hour.
- API 5xx rate above 1%.

Metrics to track (from the database): companies/filings/facts counts, duplicate-filing rate
(should be zero: run ingestion twice and compare counts), share of facts with `partial` or
`ambiguous_mapping`, webhook success rate and retry counts, requests per key, export rows/bytes.

## Rate limiting

Per-key fixed-window limits are kept in process memory. With more than one API replica, each
replica enforces the limit independently (effective limit = replicas x limit). Move the counter
to PostgreSQL before scaling out.

## Retention jobs (manual for now)

```sql
DELETE FROM api_usage WHERE occurred_at < now() - interval '90 days';
DELETE FROM notification_deliveries
 WHERE status IN ('delivered','failed') AND created_at < now() - interval '90 days';
```

## Budget

No recurring infrastructure is required until a pilot exists: the stack runs on a single small
VM or a free/entry tier (API + poller) plus an entry-tier managed PostgreSQL. Expected initial
spend is well inside the ₹15,000 planning cap from AGENTS.md; check current prices and free-tier
terms before purchasing. No paid data is used.
