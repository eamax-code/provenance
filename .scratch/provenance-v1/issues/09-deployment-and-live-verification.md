# 09: Deployment configuration and live verification report

**What to build:** The service deploys from the repo to a small host with API and poller as separate processes, migrations as a release step, secrets from the platform, and health checks. A live run against the SEC with a real contact address produces a measured freshness and data-quality report checked into docs.

**Blocked by:** 03, 04, 08

**Status:** in-progress (deployment done; live verification needs the owner's monitored contact mailbox)

- [x] Deployment manifests for one low-cost host (API, poller, managed Postgres) with documented cost under the budget cap (Fly.io and Render)
- [x] CI builds the Docker image; README deployment steps written (not yet executed against a live host)
- [ ] Live verification: `SEC_LIVE_TESTS=1` smoke test passes with a monitored contact address supplied by the owner (blocked on owner input)
- [ ] `docs/pilot-report.md` records observed poll latency distribution, quality-status shares and duplicate rate for the pilot universe (template committed; needs a live week)
