# 02: Choose a host and deploy the pilot

**What to build:** A public HTTPS deployment (API, poller with the daily listings job, managed Postgres) from the ready Fly.io or Render configuration, inside the budget cap.

**Blocked by:** 01 (US data is optional for launch but expected)

**Status:** ready-for-human (host account, domain, payment), then ready-for-agent

- [ ] Owner picks Fly.io or Render and a domain; creates the account
- [ ] Secrets set (pepper, webhook secret, admin token, SEC and markets User-Agents); migrations as release step
- [ ] `/readyz` ready; daily listings job observed once; backups enabled and a restore tested
- [ ] Monthly cost recorded against the ₹4,000 hosting cap
