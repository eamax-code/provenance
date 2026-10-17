# 03: Universe definition and resumable bulk ingestion

**What to build:** An operator defines a universe of companies (a seed list, or the top N from the SEC ticker file) and runs one command that ingests all of them within SEC fair-access limits, resumes after interruption, records per-run metrics, and can be scheduled. Polling can refresh the whole universe, not only watched companies.

**Blocked by:** 01

**Status:** ready-for-agent

- [ ] A `universe` table (or equivalent) tracks membership, priority, last attempt/success and consecutive failures per CIK
- [ ] `scripts/bulk_ingest.py` seeds the universe from a file or the ticker mapping and ingests in priority order with bounded concurrency and a budget of requests per run
- [ ] Interrupted or failed companies are retried on the next run with backoff; permanently failing CIKs are flagged, not retried forever
- [ ] Older filings referenced by the SEC `filings.files` pages are ingested on demand (configurable depth) without duplicating accessions
- [ ] Poller supports refreshing the universe on a schedule distinct from watched companies
- [ ] Unit and integration tests cover seeding, ordering, budget, resume, and pagination with fixtures
