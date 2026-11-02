# 19: Bulk Parquet snapshots (paid tier)

**What to build:** Nightly per-dataset Parquet files (US facts, filings, listings, listing events) with a manifest listing row counts, SHA-256 checksums, source dates and each source's licence. This is the "download everything" path competitors offer (inspired by londonstrategicedge.com).

**Blocked by:** 05 (legal review). It also changes a spec rule: AGENTS.md and `routes_exports.py` deliberately forbid full-universe exports.

**Status:** ready-for-human

- [ ] Owner decides whether bulk snapshots are offered, on which plan, and amends the export rule
- [ ] Then: snapshot job, object-storage upload, signed download URLs, manifest, retention
