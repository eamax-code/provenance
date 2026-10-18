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
