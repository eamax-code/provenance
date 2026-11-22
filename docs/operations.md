# Operations

## Topology

One API process (`uvicorn app.main:app`), one poller (`python scripts/poll_sec.py`), one
PostgreSQL database. The poller takes a PostgreSQL advisory lock (`pg_try_advisory_lock`) so
duplicate concurrent runs skip themselves; cron with `--once` is also safe.

## Full coverage from SEC bulk archives

The SEC rebuilds `submissions.zip` and `companyfacts.zip` nightly
(`https://www.sec.gov/Archives/edgar/daily-index/bulkdata/submissions.zip`,
`https://www.sec.gov/Archives/edgar/daily-index/xbrl/companyfacts.zip`). `scripts/sec_bulk.py
--download` fetches both with the declared User-Agent (two requests; `If-Modified-Since` makes
re-runs cheap), and `--scope facts` ingests every XBRL filer through the normal pipeline via an
archive-backed client, so results are identical to the per-company API path. Scopes: `known`
(companies in the database), `facts` (every XBRL filer), `universe`, `ciks`. Each archive is over
a gigabyte and the database grows to tens of millions of fact rows at full coverage: check disk and
database plan first, start with `--limit`, and run `--dry-run` to see counts.

## Universe and bulk ingestion

`universe_members` holds every CIK the deployment keeps fresh: seeded from a file, the SEC
ticker file (`--seed-tickers --top N`), or automatically when someone creates a watch. Each
poller pass refreshes due members within `UNIVERSE_REQUEST_BUDGET_PER_RUN` SEC requests
(two per company plus one per history page), oldest-due and highest-priority first, so a
universe of 5,000 companies at 400 requests per 5-minute pass completes a full refresh in about
2 hours while staying far below SEC's 10 requests/second guidance. Failures back off
15 min, 30 min, ... up to 24 h and disable the member after `UNIVERSE_MAX_CONSECUTIVE_FAILURES`
(see `disabled_reason`). `scripts/bulk_ingest.py --status` shows how much is due.

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
6. Create the first API key: `python scripts/create_api_key.py you@example.com --plan builder`.

The Dockerfile serves the API by default; override the command for the poller.

**Migrations before code.** Apply migrations (`alembic upgrade head`) before any process starts
or restarts on new code: the API, the poller, the hourly tracker (launchd
`com.eamax.provenance.track-filings`), chains and loaders all import whatever code is on disk
when they start. Every job entry point (`scripts/_bootstrap.py`) and `/readyz` compare the
database's alembic revision with the code's head and refuse to start ("schema behind code: run
alembic upgrade head", exit 2; `/readyz` 503 with a `schema` field) instead of failing once per
company. Create-table-only migrations are safe to apply while jobs run; a migration that alters
facts or companies waits until no pass holds their locks. When code that reads a new table is
merged locally, apply its migration in the same step.

## Backups and recovery

Backups live outside the database host's disk. On 2026-11-20 Docker Desktop's disk image was
lost with the local database in it; the only copy was a hand-made dump from 15 days earlier.

- **Dump:** `scripts/backup_db.sh` writes `provenance-<UTC stamp>.dump` (`pg_dump -Fc`), checks
  that `pg_restore --list` can read it, then keeps the newest `KEEP` (default 3). With
  `PG_CONTAINER` set it dumps through `docker exec`; otherwise it uses `DATABASE_URL`.
  About 75 seconds and 1.4 GB for the local database (November 2026).
- **Local schedule:** launchd job `com.eamax.provenance.backup-db` runs it daily at 04:15 into
  `apps/provenance-backups/` (log `~/Library/Logs/provenance-backup-db.log`). Remove with
  `launchctl bootout gui/$(id -u)/com.eamax.provenance.backup-db`.
- **Production:** nightly dump to object storage with 14-day retention, plus the provider's
  snapshots; one restore drill before launch (launch plan I-06).

### Restore

```bash
# 1. an empty database (local: a fresh container on a named volume)
docker run -d --name provenance-local-pg -e POSTGRES_USER=provenance \
  -e POSTGRES_PASSWORD=... -e POSTGRES_DB=provenance -p 127.0.0.1:5433:5432 \
  -v provenance-local-pgdata-v2:/var/lib/postgresql/data pgvector/pgvector:pg16
docker exec provenance-local-pg psql -U provenance -c "create database provenance_test"
# 2. restore (about 75 s locally; add -j 4 when restoring from a file on the host)
docker exec -i provenance-local-pg pg_restore -U provenance -d provenance --no-owner \
  < ../provenance-backups/provenance-<stamp>.dump
# 3. schema to head, then catch up on what was filed since the dump
alembic upgrade head
python scripts/sec_bulk.py --download && python scripts/sec_bulk.py --scope facts
python scripts/ingest_connections.py --insider-quarters 20 && python scripts/ingest_connections.py --showcase
python scripts/track_filings.py --days 7
python scripts/build_marts.py
```

Check afterwards: `alembic current` reports head, `/readyz` is ready, and the status page shows
filings from today. Everything except accounts, API keys, watches, deliveries and usage can be
rebuilt from public sources; the `.sec_cache` directory is disposable.

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

Per-key, per-IP and demo-key limits are fixed windows counted in PostgreSQL
(`rate_limit_counters`, one atomic upsert per check), so any number of API replicas share them.
`RATE_LIMIT_STORE` is `auto` by default (the database on PostgreSQL, memory on SQLite); `memory`
keeps counters per process, `database` forces the table.

If the database cannot be reached, each replica falls back to its own in-memory counter and logs
`rate-limit store unavailable` (at most once a minute): limits then hold per replica (effective
limit = replicas x limit) instead of failing requests. Finished windows are deleted by the daily
retention purge.

## International listings job

The poller runs the listings job once per UTC day after `MARKETS_DAILY_HOUR_UTC` (or a
platform cron runs `python scripts/ingest_markets.py --all`; see docs/deployment.md). It processes the last `MARKETS_FIRDS_DAYS_BACK` days of delta files per register
(each delta part is 10-100 MB zipped; parsing streams the XML and keeps only covered venues and
share CFI codes), then enriches up to `MARKETS_GLEIF_LOOKUPS_PER_RUN` issuers from GLEIF. Files
already processed are skipped (`market_source_files`). Run `--source esma_firds --full` once
to seed the equities universe from the weekly full file. Event counts appear in the quality
snapshot and `/v1/stats.listings`.

## Quality snapshots and reports

Every poller pass and every standalone bulk-ingest run ends by writing a row to
`data_quality_snapshots`: companies known/ingested/stale, filings and acceptance-timestamp
coverage, duplicate filings (expected 0), facts by quality status and provenance completeness,
delivery backlog and 24h outcomes, universe active/due/disabled, and the median and 95th
percentile seconds from first detection to processing for filings processed in the last 24 hours
(`latency` in `/v1/stats.quality_snapshot`). `ingestion_runs` also records SEC request totals,
retries, errors, 304 cache hits and cumulative duration per run, and `sec_by_endpoint`: responses
by endpoint and status (`{"submissions 200": 41, "archives 404": 1, "companyfacts network": 2}`).

- `python scripts/quality_report.py [--take]` prints the latest snapshot and a trend.
- `/v1/stats` exposes the latest snapshot as `quality_snapshot`.

Alert on: `facts_ambiguous / facts_total` rising, `companies_stale > 0` for two snapshots,
`oldest_pending_age_seconds > 3600`, `duplicate_filings > 0`, `sec_errors` growing run to run,
`detect_to_process_p95_s` above the poll interval plus a few minutes, and any `429` or `403` in
`sec_by_endpoint` (the SEC is throttling or refusing this User-Agent).

## Retention jobs

The poller runs the purge once per UTC day (`RETENTION_ENABLED`, default true), on every host:
it deletes `api_usage` older than `USAGE_RETENTION_DAYS`, delivered/failed
`notification_deliveries` older than `DELIVERY_RETENTION_DAYS` (pending or retrying deliveries
are never purged) and rate-limit windows older than two days. `python scripts/retention.py` runs
the same purge by hand.

## Alerts

Set `ALERT_WEBHOOK_URL` to a Slack or Discord incoming webhook and the poller posts a message when
a condition starts, again every `ALERT_REPEAT_SECONDS` (default an hour) while it lasts, and at
once if it returns after clearing:

- the last two SEC poll runs failed;
- a webhook or email delivery has waited more than an hour;
- the 95th percentile from detection to processing exceeds the poll interval plus 10 minutes;
- duplicate filings were recorded.

Without the URL the same conditions are logged as `alert` warnings. API 5xx rates and host health
come from the platform's own monitoring (Fly or Render metrics, the `/readyz` check).

## Budget

No recurring infrastructure is required until a pilot exists: the stack runs on a single small
VM or a free/entry tier (API + poller) plus an entry-tier managed PostgreSQL. Expected initial
spend is well inside the ₹15,000 planning cap from AGENTS.md; check current prices and free-tier
terms before purchasing. No paid data is used.

## Local Postgres container

The local database runs in Docker as `provenance-local-pg` (pgvector/pgvector:pg16) on the named
volume `provenance-local-pgdata-v2`, published on 127.0.0.1:5433. Parallel query workers need
more than Docker's default 64 MB of /dev/shm (2026-11-21: "could not resize shared memory
segment ... No space left on device"), so the container runs with `--shm-size=1g`. To recreate
it (data stays on the volume; stop jobs first, about a minute of downtime):

```
pw=$(docker inspect -f '{{range .Config.Env}}{{println .}}{{end}}' provenance-local-pg \
     | grep '^POSTGRES_PASSWORD=' | cut -d= -f2-)
docker stop -t 90 provenance-local-pg && docker rm provenance-local-pg
docker run -d --name provenance-local-pg --shm-size=1g -p 127.0.0.1:5433:5432 \
  -e POSTGRES_DB=provenance -e POSTGRES_USER=provenance -e POSTGRES_PASSWORD="$pw" \
  -v provenance-local-pgdata-v2:/var/lib/postgresql/data pgvector/pgvector:pg16
```

Recreated this way on 2026-11-22 at 03:01Z; `max_parallel_workers_per_gather` (set to 0 as a
stopgap during the 1.4.0 pass) was reset with `ALTER SYSTEM RESET` (one statement per psql call:
ALTER SYSTEM cannot run in a transaction block) and a parallel aggregate over financial_facts ran
with 2 workers.

## Post-chain checklist

Run after a mapping pass or a chain (facts, tracker, ipo_terms, marts, backup) ends. Steps that
wait on something are written here, not remembered.

1. `alembic current` equals head; every create-table migration merged since the chain started
   is applied (the schema guard refuses jobs otherwise).
2. `python scripts/check_mapping.py`: no facts on an older mapping, other than the known rows
   the SEC's company facts no longer publish (122 rows at 5 co-registrants and a SPAC after the
   1.4.1 pass; re-ingesting them from the SEC changes nothing). Any other company listed was
   missed by the pass.
3. Marts rebuilt (`scripts/build_marts.py`), coverage snapshot refreshed; mart counts compared
   with the previous run.
4. `python scripts/quality_doc.py --out docs/data-quality-<date>.md`; spot check all "same".
5. Backup: the chain's dump lists every table (`pg_restore --list`); the daily launchd backup's
   last log line is "backup ok".
6. K-05: `python scripts/detect_successions.py` stores the reviewed pairs; new pairs it reports
   as not reviewed go to `app/data/successions_reviewed.csv` after a hand check.
7. Loads that waited for the chain: E-1 13F (`scripts/load_13f.py`), E-2 releases
   (`scripts/read_releases.py`), E-3 auditors (`scripts/load_auditors.py`), K-04b tickers
   (`scripts/load_ticker_history.py`), E-4 segments (`scripts/load_segments.py`).
8. Restart long-running processes (API, poller) only after step 1.

## Load smoke (R-2), 2026-11-22

`scripts/load_smoke.py` against a local 2-worker API (`uvicorn --workers 2`, mapping 1.4.0,
25.7M facts, PostgreSQL in Docker), 50 requests a second open-loop for 300 s (15,000 requests),
one Enterprise test key (revoked afterwards); the per-address limits on the keyless endpoints
were raised on that instance only (`PUBLIC_RATE_LIMIT_PER_MINUTE`,
`STATS_RATE_LIMIT_PER_MINUTE`), since every request came from one address.

| Endpoint | p50 ms | p95 ms | p99 ms | Errors | Target p95 |
|---|---|---|---|---|---|
| facts | 17.3 | 23.8 | 29.9 | 0 | < 500 ms, pass |
| screen | 31.5 | 40.1 | 48.9 | 0 | < 2 s, pass |
| search | 30.5 | 38.7 | 49.5 | 0 | |
| MCP get_figures | 17.9 | 26.9 | 33.6 | 0 | |
| stats | 4.3 | 7.0 | 8.9 | 0 | < 100 ms, pass |
| coverage | 7.3 | 10.3 | 12.1 | 0 | < 100 ms, pass |
| public overview (showcase, 20 req/s, 60 s) | 16.4 | 20.9 | 24.8 | 0 | |

A point-in-time overview that misses the cache took 68-72 ms. The 50 req/s run's overview row
counted companies outside the showcase (404s), so the overview is reported from the separate
showcase run.

## Restore drill (R-3), 2026-11-22

The daily dump `provenance-2026-11-22T0351Z.dump` (4.3 GB, custom format, 56 tables; written by
the launchd backup job) restored into a scratch database in the same container and dropped
afterwards:

```
docker exec provenance-local-pg psql -U provenance -d postgres -c "CREATE DATABASE provenance_restore_drill"
docker cp ../provenance-backups/provenance-2026-11-22T0351Z.dump provenance-local-pg:/tmp/drill.dump
docker exec provenance-local-pg pg_restore -U provenance -d provenance_restore_drill -j 4 --no-owner /tmp/drill.dump
```

- Copy into the container 29 s; `pg_restore -j 4` 278 s; 307 s in all (exit 0). The parallel
  restore needs the dump as a file inside the container (not piped on stdin).
- Restored size 26 GB (the live database is 33 GB with table bloat).
- Row counts identical to live for financial_facts (25,673,172), filings (8,785,467), companies,
  mart_company (817 non-USD reporting currencies), mart_financials, insider_transactions,
  company_lei, gleif_entities and registrant_successions; alembic at the same head
  (a6d2e8f4c0b3). api_keys differed by one key created after the dump.
- Disk: the Docker VM had 379 GB free; a full drill needs about 30-40 GB free beside the live
  database.

To recover for real: stop the API, poller and launchd jobs; create an empty database (or a new
volume), `pg_restore -j 4 --no-owner` the newest dump that `pg_restore --list` reads, run
`alembic upgrade head` (the schema guard refuses jobs until it matches), rebuild marts if the
dump predates a mart change, then start the processes.
