# 04: Data quality snapshots, retention jobs and operator reports

**What to build:** After each ingestion run the service records a quality snapshot (facts by status, duplicate rate, companies stale, delivery backlog, SEC request outcomes), operators can print a quality report, retention purges run from one command, and the stats endpoint reports the latest snapshot.

**Blocked by:** 02, 03

**Status:** ready-for-agent

- [ ] `data_quality_snapshots` written at the end of each run with the metrics listed in AGENTS.md section 12
- [ ] SEC request outcomes (status, retries, duration) are persisted per run in aggregate
- [ ] `scripts/quality_report.py` prints the latest snapshot and trend; `scripts/retention.py` purges usage/deliveries past the documented window
- [ ] `/v1/stats` includes the latest snapshot summary
- [ ] Tests cover snapshot computation and retention boundaries
