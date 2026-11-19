# Deployment

Two process groups share one Docker image: the API (`uvicorn app.main:app`) and the poller
(`python scripts/poll_sec.py`). Migrations run as a release step. One managed PostgreSQL.

## Option A: Fly.io (`deploy/fly.toml`)

```bash
fly launch --no-deploy --copy-config --config deploy/fly.toml   # creates the app
fly postgres create --name provenance-db --initial-cluster-size 1 --vm-size shared-cpu-1x --volume-size 1
fly postgres attach provenance-db --app provenance-api            # sets DATABASE_URL (postgres://)
fly secrets set SEC_USER_AGENT="Provenance/0.1.0 contact=<monitored mailbox>" \
  API_KEY_PEPPER="$(python -c 'import secrets;print(secrets.token_urlsafe(48))')" \
  WEBHOOK_SIGNING_SECRET="$(python -c 'import secrets;print(secrets.token_urlsafe(48))')" \
  ADMIN_TOKEN="$(python -c 'import secrets;print(secrets.token_urlsafe(32))')"
fly volumes create sec_cache --size 1 --region iad
fly deploy --config deploy/fly.toml
fly scale count api=1 poller=1
fly ssh console -C "python scripts/create_api_key.py you@example.com --plan internal"
fly ssh console -C "python scripts/bulk_ingest.py --seed-file data/universe.sample.txt --seed-only"
```

`DATABASE_URL` from `fly postgres attach` starts with `postgres://`; SQLAlchemy needs
`postgresql+psycopg://`. Set it explicitly: `fly secrets set DATABASE_URL=postgresql+psycopg://...`.

## Option B: Render (`deploy/render.yaml`)

Create a Blueprint from the repo. Fill `SEC_USER_AGENT` and `ADMIN_TOKEN` when prompted; copy the
generated pepper and webhook secret into the worker's environment so both processes share them.

## Option C: any VM with Docker Compose

`docker compose up -d` runs db, migrate, api and poller. Put a TLS-terminating proxy (Caddy or
nginx) in front of port 8000 and set `.env` from `.env.example` with real secrets.

## Daily international-listings job

- **Fly.io and Docker Compose**: the poller process runs it (`MARKETS_DAILY_ENABLED=true`) once
  per UTC day after `MARKETS_DAILY_HOUR_UTC` (default 10:00, after ESMA/FCA publish). No extra
  machine. The poller's single-run lock prevents duplicates if two pollers ever overlap.
- **Render**: `provenance-markets-daily` is a native cron service (`45 9 * * *` UTC) running
  `scripts/ingest_markets.py --all`; the worker has `MARKETS_DAILY_ENABLED=false` so it does
  not run twice.
- **Plain cron**: `45 9 * * * cd /app && python scripts/ingest_markets.py --all`.
- Either way the run is recorded under `ingestion_runs.source = markets:daily`, so a second
  trigger on the same day is a no-op.

## Connections graph data (ADR 0011)

- Once after the first deploy: `python scripts/ingest_connections.py --insider-quarters 20`
  (about 8 MB per quarter, ten minutes for five years), then
  `python scripts/ingest_connections.py --showcase`.
- After that the poller keeps it current (`CONNECTIONS_DAILY_ENABLED=true`, default): once a
  UTC day it checks the SEC's data set page, loads a new quarter when one appears and rereads the
  showcase companies' exhibit 21, 13D/G filings and newest Forms 4. Keyed API callers trigger the
  same read for any other company, at most once a week per company.

## Filings tracker (ADR 0012)

- The poller reads EDGAR's new filings every hour (`FILINGS_TRACKER_ENABLED=true`,
  `FILINGS_TRACKER_INTERVAL_SECONDS=3600`): it refreshes covered companies that filed and adds
  companies going public. After a deploy or any downtime, catch up once with
  `python scripts/track_filings.py --days 7`; `--status` shows what it has seen and done.
- Where the poller does not run (a platform cron only), schedule
  `0 * * * * cd /app && python scripts/track_filings.py` instead.

## Before the first deploy (checked locally on 2026-11-15)

The production image was built from this repository and run with `APP_ENV=production` against
a copy of the data. `/readyz` answered `ready`, migrations were at head, `/poc/` returned 404,
HSTS and the content security policy were sent, MCP answered, and account sign-in answered 503
because no email provider was set. `.dockerignore` keeps the image to `app/`, `scripts/`,
`site/` and the build files (no SEC archives, tests or prototypes).

Settings to fill in:

| Setting | Why |
| --- | --- |
| `SEC_USER_AGENT` | Product name and a monitored contact address; the SEC requires it |
| `API_KEY_PEPPER`, `WEBHOOK_SIGNING_SECRET`, `ADMIN_TOKEN` | New random values for production; never reuse development ones |
| `PUBLIC_BASE_URL` | The domain, for sign-in links, the sitemap and robots.txt; also set `origin` in `site/shell/site.json` and run `scripts/sync_site_shell.py` so canonical and preview tags are absolute |
| `EMAIL_PROVIDER=smtp`, `SMTP_*`, `EMAIL_FROM` | Sign-in links and email watches (ticket 06); without them sign-in points visitors to the key request form |
| `PUBLIC_SHOWCASE_CIKS` | The companies on the public pages and open to the demo key (the deploy files list twelve) |
| `LLM_ENABLED`, `LLM_BASE_URL` | Where chat's model runs (GH #13); with it off, chat still answers from data with charts and tables |

## After the first deploy

1. `GET /readyz` must return `ready`; it lists any configuration problem (never secret values).
2. Issue the first key, seed a universe, run `scripts/bulk_ingest.py` until `--status` shows
   `due_now: 0`, then let the poller keep it fresh.
3. Create a watch with a real HTTPS receiver and confirm a signed delivery (`GET /v1/watches/{id}/deliveries`).
4. Run `scripts/quality_report.py` after a day and record the numbers in `docs/pilot-report.md`.

## Cost (planning, check current prices)

| Item | Monthly |
| --- | --- |
| Fly shared-cpu-1x 512 MB x2 (api + poller), auto-stop on api | about US$4-8 |
| Fly Postgres single node 1 GB | about US$2-5 |
| Fly volume 1 GB for the SEC response cache (poller) | about US$0.15 |
| Domain | about US$12/year |

Roughly ₹700-1,200 per month, inside the ₹4,000 hosting cap in AGENTS.md for a multi-month
pilot. Render's starter plans are similar. No paid data.

## Backups and recovery

Fly Postgres and Render both take daily snapshots. Everything except keys, watches, usage and
key requests can be rebuilt from the SEC by re-running bulk ingestion. After a restore run
`alembic upgrade head`, then `scripts/poll_sec.py --once`.
