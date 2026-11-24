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
4. Start the API with 2 workers (`uvicorn --workers 2`) behind HTTPS; health check `GET /healthz`, readiness
   `GET /readyz`. One worker is too tight once full-text search is in the mix (R-2 for Q-01 below).
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

## Ships with the next deploy

Applied locally, not yet on any deployed database. Apply in this order with `alembic upgrade
head`, before the new code starts:

| Revision | What | Notes |
|---|---|---|
| `d2e4f6a8b0c1` | Q-03: partial index on the transaction date of open-market insider lines (codes P and S) | `CREATE INDEX CONCURRENTLY` (PostgreSQL): does not block insider loads, takes a few minutes |
| `e3f5a7b9c1d2` | Q-02: `thirteenf_issuer_names` (issuer name as filed, per security and quarter) | create table |
| `f4a6b8c0d2e3` | Q-02: `thirteenf_security_stats`, `thirteenf_filing_scale`, `thirteenf_activity` | create tables |
| `a5b7c9d1e3f4` | Q-02: the majority class title on `thirteenf_security_stats` | adds a column to a table filled only by the batch |
| `b6c8d0e2f4a5` | Q-02: `thirteenf_reported_by` (the managers a 13F notice names) | create table |
| `a1b3c5d7e9f2` | S-05: `companies.fiscal_year_offset` (fiscal-year naming as the company's latest 10-K words it) | adds a nullable column (null keeps today's end-year labels); then `scripts/set_fiscal_year_offsets.py --dry-run --fetch` (reads each candidate's latest 10-K or 20-F through SecClient into the document cache, stops on 403/429), then without `--dry-run`/`--fetch` (stores from the cache), then `scripts/build_marts.py` (the marts store fiscal years) |
| `f0a2b4c6d8e1` | Q-07: `schedule_13d_purposes` (Item 4 of structured 13Ds, as filed) | create table; then `scripts/load_13d_purposes.py --dry-run` (fetches into the document cache through SecClient, stops on 403/429), then without `--dry-run` (stores from the cache) |
| `e9f1a3b5c7d9` | Q-04: `dividend_facts` (dividends per share, the same columns as `financial_facts`) | create table; then `scripts/load_dividend_facts.py` (dry run, then write) and `--since-bulk` (companies ingested since the bulk file, from the cache) |
| `d8e0f2a4b6c7` | F-03d: `insider_filing_text` (signatures, remarks and footnotes of forms with an entity owner) | create table; then `scripts/load_insider_filing_text.py` (dry run, then write) and `scripts/fill_insider_filing_text.py` (forms read as filed, from the document cache), then `scripts/correct_insider_activity.py --change f03d` and `--change f03b` (dry run, then `--write`) |
| `c7d9e1f3a5b6` | F-03c: `status`, `retracted_at`, `retraction_reason`, `corrected_at`, `previous_values` on `insider_activity` | adds columns (status defaults to active); then `scripts/correct_insider_activity.py` (dry run, then `--write`) |

Then the Q-02 data, each from the repo root: `scripts/load_13f_names.py`,
`scripts/load_13f_reported_by.py`, then the managers' statistics batch
`scripts/build_13f_stats.py`. Until the batch has run, the managers' portfolio and activity
responses carry a note that the statistics lag the holdings.

**The 13F batch is part of every 13F load (2026-11-25).** `scripts/load_13f.py` (every mode that
writes holdings or CUSIP links: data sets, schedules, `--deep`, `--name-rule`,
`--remove-reviewed --apply`) and `scripts/load_13f_edgar.py` end with
`fund_managers.after_load`, which rebuilds the statistics for every fully loaded quarter and
records what they were built from (the holdings version and the CUSIP map). If the batch fails
the load exits 1 with "13F loaded, but the managers' statistics batch failed: run
scripts/build_13f_stats.py"; rerun that script. Any change of holdings or links not followed by
the batch makes the portfolio and activity responses say so (checked once a minute per process).
A test fails when a script that writes 13F holdings or links does not call the batch.

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

## Incidents (runbook)

Each case: the symptom, how to confirm it, then the commands. Local names are used throughout
(container `provenance-local-pg`, launchd jobs `com.eamax.provenance.*`); in production the same
steps apply through the provider's console and `DATABASE_URL`. Stop and ask before anything that
deletes data. Write what happened, when and what was done in docs/status-<date>.md.

### Database down

- **Symptom:** `/readyz` returns 503 with a database error; the tracker log says "database not
  reachable ... skipped"; jobs fail at start.
- **Confirm:**
  ```
  docker ps --filter name=provenance-local-pg --format '{{.Status}}'
  docker exec provenance-local-pg pg_isready -U provenance
  curl -s localhost:8000/readyz
  ```
- **Fix:** `docker start provenance-local-pg`, then `pg_isready` again and `/readyz`. If Docker
  itself is down, start Docker Desktop first. If the container will not start, read
  `docker logs --tail 100 provenance-local-pg` before anything else; never remove the volume
  `provenance-local-pgdata-v2`. A volume that is lost is a restore (below).

### Database disk full

- **Symptom:** writes fail with "could not extend file" or "No space left on device"; loads stop.
- **Confirm:**
  ```
  docker system df
  docker exec provenance-local-pg df -h /var/lib/postgresql/data
  df -h ..                       # the host disk that holds Docker and the backups
  docker exec provenance-local-pg psql -U provenance -c "select pg_size_pretty(pg_database_size('provenance'))"
  ```
- **Fix:** stop the loads first. Free host space (old files in `.sec_cache/`, `.markets_cache/` and
  `.sec_bulk/` can be fetched again; keep the newest backup). Grow Docker Desktop's disk image if
  it is the limit. Never delete database rows to make room. Afterwards `VACUUM (ANALYZE)` the
  tables a failed load touched.

### /dev/shm full (parallel queries)

- **Symptom:** "could not resize shared memory segment ... No space left on device" on large
  queries (marts, the quality report).
- **Confirm:** `docker exec provenance-local-pg df -h /dev/shm` (should be 1G, not 64M).
- **Fix:** recreate the container with `--shm-size=1g` (Local Postgres container, above; data
  stays on the volume). As a stopgap without a restart:
  `docker exec provenance-local-pg psql -U provenance -c "ALTER SYSTEM SET max_parallel_workers_per_gather = 0"`
  then `... -c "select pg_reload_conf()"`; undo with `ALTER SYSTEM RESET` after the recreate.

### SEC 403 or 429

- **Symptom:** logs show `sec request error` with status 403 or 429; every SEC job slows down at
  once (the machine-wide limiter pauses all processes: 600 s after a 403, 30 s after a 429).
- **Confirm:**
  ```
  grep -h '"status": 40[3]\|"status": 429' ~/Library/Logs/provenance-track-filings.log | tail -5
  cat ~/.cache/provenance/sec-rate   # the shared limiter's state, pause included
  ```
- **Fix:** back off; let the pause run. Never raise `SEC_MAX_REQUESTS_PER_SECOND` (8) and never
  bypass `SecClient`. Stop the least important SEC job (E-4b+ relabels, E-5 connections) if
  several run. Check that `SEC_USER_AGENT` carries a working contact. A 403 that keeps coming
  back after the pause means the SEC has blocked the address: stop all SEC jobs and wait an
  hour before one test request with `python scripts/sec_fetch.py <a filing index URL>`.

### Hourly tracker skipping

- **Symptom:** the status page's latest filing is hours old; the tracker log shows "skipped".
- **Confirm:**
  ```
  tail -20 ~/Library/Logs/provenance-track-filings.log
  launchctl list | grep provenance        # the job and its last exit status
  docker exec provenance-local-pg psql -U provenance -c "select name, value, updated_at from job_state where name like 'filings_tracker%'"
  ```
  "another run is in progress": a run still holds the lock (PostgreSQL advisory lock; the
  `.track_filings.lock` file on SQLite). "database not reachable": see Database down. "refusing
  to start: schema behind code": run `alembic upgrade head`.
- **Fix:** if a run is stuck, find it with `ps aux | grep track_filings` and stop that process
  only; the next hourly run catches up from `filings_tracker.daily_index`. To catch up by hand:
  `python scripts/track_filings.py --days 2`. Reload the job after editing its plist with
  `launchctl bootout gui/$(id -u)/com.eamax.provenance.track-filings` and `launchctl bootstrap
  gui/$(id -u) ~/Library/LaunchAgents/com.eamax.provenance.track-filings.plist`.

### A bad mapping found after a pass

- **Symptom:** a spot check, the quality report or a user shows wrong figures from a mapping
  version that was just rolled out.
- **Confirm:** reproduce on one company (`/v1/companies/{cik}/facts?metric=...` shows the value and
  `mapping_version`); compare with the 10-K as filed; `python scripts/quality_doc.py --out
  /tmp/q.md` and diff the per-metric table with the last good report.
- **Fix, forward (preferred):** correct the rule, bump `MAPPING_VERSION` (a changed rule is always
  a new version), add a test with the case, run the suite, then the full pass
  (`python scripts/sec_bulk.py --scope facts`), `check_mapping.py`, `build_marts.py` and the
  quality report. Each stored fact carries the version that produced it, so as_of answers stay
  explainable.
- **Fix, back to a backup** (when the pass also broke other tables): take a dump of the current
  state first (`PG_CONTAINER=provenance-local-pg scripts/backup_db.sh`), then restore the last
  dump taken before the pass (Restore from backup, below), then `alembic upgrade head`,
  `check_mapping.py` and `build_marts.py`. Facts loaded since that dump come back with the next
  tracker runs and a `sec_bulk.py --scope facts` pass.
- **Tell users:** add a dated entry to the public changelog (`site/changelog/`, through
  provenance-ui) naming the mapping version, the metrics and companies affected, the wrong and
  the right figures, and when it was corrected. A changed figure is a restatement of our own
  output and is listed plainly.

### A leaked API key

- **Symptom:** a key appears in a public place (a repository, a paste, a screenshot) or its usage
  jumps.
- **Confirm (by prefix, never by the full key):**
  ```
  docker exec provenance-local-pg psql -U provenance -c "select id, key_prefix, plan, label, last_used_at, revoked_at from api_keys where key_prefix = 'prv_XXXX'"
  docker exec provenance-local-pg psql -U provenance -c "select date_trunc('hour', occurred_at) h, count(*) from api_usage where api_key_id = '<id>' group by 1 order by 1 desc limit 24"
  ```
- **Revoke at once:** the owner can do it on /account (`DELETE /v1/account/keys/{id}`); as the
  operator:
  ```
  docker exec provenance-local-pg psql -U provenance -c "update api_keys set revoked_at = now(), is_active = false where id = '<id>'"
  ```
  The next request with the key gets 401.
- **Rotate:** issue the owner a new key (`python scripts/create_api_key.py <owner email> --plan
  <plan> --label "rotated <date>"`; the raw key prints once and is never stored) and send it over
  the channel they registered with. Update webhook secrets the owner derived from the old key.
  Never paste a key into a log, a ticket or a message; the R-2 script once printed one, and that
  key was revoked.

### Restore from backup

- **When:** the database is lost or corrupted, or a bad pass needs undoing (above).
- **Confirm the dump first:** `docker exec -i provenance-local-pg pg_restore --list <
  ../provenance-backups/provenance-<stamp>.dump | grep -c 'TABLE DATA'` (56 tables in November
  2026).
- **Restore:** follow "Restore" under Backups and recovery (an empty database, `pg_restore`, then
  `alembic upgrade head` and the catch-up commands). The R-3 drill (below) restored the 2026-11-22
  dump in 307 s with identical row counts. Afterwards: `/readyz` is 200, `check_mapping.py`
  reports "0 unexpected old rows", the status page shows today's filings, and the post-chain
  checklist runs.

## Post-chain checklist

Run after a mapping pass or a chain (facts, tracker, ipo_terms, marts, backup) ends. Steps that
wait on something are written here, not remembered.

1. `alembic current` equals head; every create-table migration merged since the chain started
   is applied (the schema guard refuses jobs otherwise).
2. `python scripts/check_mapping.py` reports "0 unexpected old rows (N reviewed exceptions)"
   and exits 0. Reviewed exceptions are listed in `app/data/mapping_exceptions.csv` (company,
   mapping, row count, reason, date checked): rows the SEC's company facts no longer publish (122
   at 5 co-registrants and a SPAC after the 1.4.1 pass; re-ingesting them changed nothing). Any
   other old row, or more rows than reviewed, fails the check: the pass missed that company.
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

## Rehearsal re-run, 2026-11-22 evening (before mapping 1.5.0)

The production image (`provenance:rehearsal`, built from 0df9281) on :8790 with `APP_ENV=production`
and 2 workers against the local database; temporary Builder and Enterprise keys, revoked after.

R-1 `scripts/smoke_prod.py --receiver 8099 --receiver-host host.docker.internal`: 7 of 8, as in the
morning; readyz reports only the rehearsal settings (private webhook destinations, console email)
and `NEWS_PROVIDER=google_rss` (owner decision).

R-2 `scripts/load_smoke.py --rps 50 --seconds 300`, p95 in ms (morning in brackets):

| Endpoint | Morning mix (7 endpoints) | Full mix (9: + company overview, ownership) | Full mix after fa65fd9 + 82f3a92 |
|---|---|---|---|
| facts | 24.7 (23.8) | 122.5 | 21.7 |
| screen | 39.8 (40.1) | 162.3 | 37.4 |
| search | 41.6 (38.7) | 135.4 | 40.8 |
| MCP get_figures | 31.2 (26.9) | 138.6 | 28.5 |
| stats | 7.7 (7.0) | 38.6 | 8.5 |
| coverage | 10.3 (10.3) | 62.5 | 9.3 |
| company overview (`/v1/companies/{cik}`) | | 76.2 | 23.5 |
| ownership | | 408.6 (p50 254) | 25.6 (p50 16.1) |

No errors in either run (the public overview's 404s are companies outside the showcase). All
targets pass. Ownership is CPU-bound in Python (a large holder list: Apple about 6,000
managers per quarter, read twice), so with it in the mix the 2 workers saturate and every
other endpoint's p95 rises 3-5x. The first full-mix run, before 0df9281 (which reads plain rows
and only the holders' filings), collapsed: requests held a pooled connection while waiting for a
second one (rate limits, usage metering), all 30 connections (2 x 15) were held and requests
timed out after 30 s. Both follow-ups went in the same evening: fa65fd9 gives rate limits and usage
metering a small pool of their own (3 + 2 connections, 2 s timeout) that request handlers cannot
starve, and 82f3a92 caches the latest-quarter ownership block per process, keyed on the company's
links, cover shares, quarter, page and the 13F holdings version that every load bumps (never with
as_of). The last column is the same full mix on the rebuilt image: ownership p95 25.6 ms (target
under 100), facts and screen back at the morning's (targets 1.5x: about 36 and 60 ms), no errors.

## R-2 for the Explorer endpoints and the keyless cache, 2026-11-23 (before the freeze)

`scripts/load_smoke.py` (now with `--watchlist` and `--demo`) against a local 2-worker API on
:8791 at 7688750 (mapping 1.5.0, local PostgreSQL), 50 requests a second open-loop. One temporary
Enterprise key (revoked afterwards); per-address limits raised on that instance only, since every
request came from one address. The global demo ceiling (1,200 a minute) stayed at its default.
The machine was shared with other sessions (load average 5-10).

The first run (13 endpoints with watchlist rows) saturated: 35.6 req/s achieved, p95 3-5 s everywhere.
Measured alone, watchlist rows took about 480 ms and JPMorgan's timeline 535 ms: the timeline read
all 28,000 of JPMorgan's filings for every page. b859cdf reads only the filings a page needs (JPMorgan
page 17 ms, identical pages on six companies). After it, 300 s, 15,000 requests, 0 errors:

| Endpoint | p50 ms | p95 ms | p99 ms | Target p95 |
|---|---|---|---|---|
| facts | 22.9 | 79.6 | 769 | < 500, pass |
| screen | 34.8 | 77.7 | 699 | < 2,000, pass |
| search | 33.6 | 63.5 | 680 | |
| MCP get_figures | 20.4 | 40.7 | 837 | |
| company (`/v1/companies/{cik}`) | 16.7 | 26.0 | 660 | |
| ownership | 18.0 | 26.6 | 697 | < 100, pass |
| stats | 3.6 | 6.8 | 322 | < 100, pass |
| coverage | 5.4 | 8.6 | 429 | < 100, pass |
| statements (X-02) | 26.1 | 54.4 | 684 | |
| timeline (X-05) | 32.5 | 45.6 | 1,806 | |
| keyed overview (X-01a) | 109.4 | 169.1 | 1,386 | |
| watchlist rows (X-07, 6 companies) | 82.1 | 116.6 | 1,181 | |

The p99s of 300-800 ms on every endpoint, cheap ones included, are stalls on a shared machine,
not one endpoint. facts and screen p95 are above last night's 21.7 / 37.4 ms with four heavier
endpoints in the mix (keyed overview and watchlist rows are about 35% of the CPU), still well
inside their targets.

Keyless burst (`--demo`, 120 s, 6,000 requests): every showcase page (overview, income
statement, timeline, insiders, 5% holders, ownership) of the six showcase companies, with the
demo key. 0 errors, no 429s. p50 1.2-5.1 ms, p95 16-74 ms (cache hits: no database). The p99
(timeline 5.6 s, overview 1.9 s) is the cold start: both workers miss the same keys at once
before the first response is cached (no single-flight; acceptable, since it happens once per
data change per worker).

Single-flight (7aa6b4d), the same burst on a fresh server with no data load running: p95 holders
6.6 ms (was 16.3), insiders 9.0 (27.8), overview 47.6 (73.5), ownership 11.6 (17.7), statements
17.7 (27.3), timeline 92.7 (42.4); p99 timeline 4.9 s (5.6), overview 1.9 s (1.9). Duplicate
computes are gone (tests: 6 concurrent ownership misses and 8 cold demo requests each compute
once), but the cold p99 is the first wave of distinct cold pages (36 per worker, all computed at
once under the GIL, the timelines' 13F quarters heaviest), which single-flight cannot shorten.
Warming the showcase pages when a worker starts or the data version changes would (after the
freeze). A first run while E-4b+ was writing segment labels (about 1,000 rows a second) showed
the cache emptying at every 30 s version check: during a load the cache acts like a 30 s TTL.

The timeline p95 rising from 42 to 93 ms was not like for like: the 42 ms run had no data load,
so one cold wave. An A/B under the same conditions, alternating A, B, A, B: A is ee80b01 (before
single-flight, exported with git archive), B is 7aa6b4d, each on a fresh 2-worker server, 120 s at
50 req/s, with E-4b+ writing throughout, so the cache went cold every 30 s. Timeline:

| Run | p50 ms | p90 ms | p95 ms | p99 ms | cold computes | slowest compute |
|---|---|---|---|---|---|---|
| A, before | 0.8 | 39.5 | 3,918 | 9,227 | 102 | 11.7 s |
| B, single-flight | 1.3 | 2.9 | 106 | 4,927 | 35 | 6.3 s |
| A again | 1.7 | 23.2 | 1,809 | 8,902 | 87 | 10.9 s |
| B again | 1.6 | 3.4 | 70 | 4,646 | 44 | 6.1 s |

Single-flight cuts the timeline's cold computes by about 60% and halves the p99; waiters queueing
behind a slow leader cost less than the duplicate computes they replace. All four runs: 0 errors.

## Final rehearsal, 2026-11-23 (before the 08:30 freeze)

The production image built from 1bfc4e2 (`provenance:rehearsal-1123`), on :8790 with
`APP_ENV=production`, 2 workers, against the local database; one temporary Builder key, revoked
after. R-1 `scripts/smoke_prod.py --receiver 8099 --receiver-host host.docker.internal`, now with
the Explorer checks: 13 of 14. readyz reports only the rehearsal settings (private webhook
destinations, console email, `NEWS_PROVIDER=google_rss`, the owner's decision), as in every
rehearsal.

| Check | Result | ms | Detail |
|---|---|---|---|
| readyz | rehearsal settings | 17 | database ok, schema ok |
| demo key: data and limits | pass | 89 | 20/min, 10 rows |
| keyed facts with as_of | pass | 20 | FY2023 filed 2023-11-03 |
| plans | pass | 3 | five plans |
| MCP tools/list and a call | pass | 32 | 15 tools |
| event stream (SSE) | pass | 8 | |
| type watch (Builder) | pass | 43 | immediate |
| signed webhook to a receiver | pass | 556 | delivered and verified |
| statements (X-02) | pass | 65 | Apple 14 columns, 17 rows, split_break FY2017/FY2018 |
| timeline (X-05) and its cursor | pass | 1,246 | 10 + 10 items, no overlap (cold: the 13F block) |
| keyed overview (X-01a) | pass | 366 | 160 KB, no-store |
| watchlist create, rows, delete (X-07) | pass | 52 | Archives links in rows |
| MCP company_statements and company_timeline | pass | 53 | valid JSON |
| keyless showcase (cached) | pass | 28 | miss, then hit |

Chat evals on 1bfc4e2: the live eval (`scripts/live_chat_eval.py`, 20 questions against the
local database) 20/20, exact figures 15/15, uncited figure sentences 0; the fixture eval
(`tests/integration/test_chat_eval.py`) 64/64, exact figures 36/36, C-06 7/7, uncited 0.

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

## R-2 for the 24 Nov endpoints (2026-11-24 03:57 IST)

`scripts/load_smoke.py --rps 25 --seconds 180` against a scratch server on HEAD fe50312 (one
uvicorn worker, local Postgres, a temporary enterprise key revoked afterwards), 4,500 requests,
0 errors. Target p95 under 500 ms for each new endpoint:

| Endpoint | p50 ms | p95 ms | p99 ms |
| --- | --- | --- | --- |
| /insider-plans | 11 | 15 | 24 |
| /comment-letters | 10 | 20 | 59 |
| /executive-pay | 20 | 30 | 51 |
| /changes | 21 | 30 | 56 |
| /v1/companies/search (palette names) | 30 | 42 | 84 |
| /corporate-tree | 24 | 50 | 70 |
| /timeline | 33 | 50 | 377 |
| /calendar | 17 | 61 | 80 |
| /v1/search | 51 | 63 | 95 |
| /v1/calendar?ciks= (5 companies) | 65 | 85 | 147 |

An earlier pass at 03:20 under a load average of 7 (Form 144 prefetch, letters and 10-K reads
running) had /v1/search at 527 ms p95: contention, not the endpoint (single requests 25-55 ms).

## R-2 for Q-01 full-text search (2026-11-24 evening)

`scripts/load_smoke.py` against a scratch server on HEAD 87fad5b (one uvicorn worker, local
Postgres, a temporary enterprise key revoked afterwards), load average 6-8 on the machine.

| Run | Requests | Search p50 | Search p95 | Search p99 | Errors |
| --- | --- | --- | --- | --- | --- |
| `filing search` alone, 30 query shapes (15 queries x both sorts), 5 req/s, 180 s | 900 | 125 | 222 | 272 | 0 |
| the 24 Nov mix plus `filing search`, 25 req/s, 120 s | 3,000 | 121 | 298 | 1,303 | 0 |

The shapes: words, phrases, the stop-word phrase "will be available", or-groups, exclusions,
and section, form, date and cik filters. With search in the mix the other endpoints' p95 rose
to 70-440 ms (timeline 722 ms) and every endpoint had p99 stalls of about 1 s; the same mix
without search kept them under 105 ms (except /v1/search at 230 ms under that load). Production
therefore runs 2 workers. Before launch: re-run the mix plus search at 2 workers; if timeline
is still over 500 ms p95, it gets a ticket.

Speed decisions behind these numbers: the GIN index answers the match alone (sequential scans
off for that query; a common word otherwise read every stored vector, about 650 ms); filters
and dates come from an in-process section map, not a join of matches to filings; a quoted
phrase is checked chunk by chunk with the phrase operator in the select list before texts are
read; relevance ranks the newest 2,000 matches; a quoted single word matches by stem (exact
single words read thousands of texts, 0.7-1.5 s).
