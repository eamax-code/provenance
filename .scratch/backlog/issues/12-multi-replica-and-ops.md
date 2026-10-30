# 12: Production hardening for more than one API replica

**What to build:** Per-key and per-IP rate limits and the demo-key limits are in process memory, so two replicas double them. Move counters to Postgres; schedule the retention job; alert on repeated ingestion failures and delivery backlog as described in docs/operations.md.

**Blocked by:** 02

**Status:** ready-for-agent

- [ ] Shared rate-limit store with tests; documented behaviour on DB outage
- [ ] Retention job scheduled in each deploy config; alert hooks documented or wired
