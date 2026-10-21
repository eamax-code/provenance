# 01: Listings domain, idempotent ingestion with events, authenticated API

**What to build:** Venues, issuers, instruments and lifecycle events exist as a domain with a source-agnostic record contract; ingesting records twice changes nothing; new listings, delistings, suspensions, name changes and source-stated IPOs become idempotent events; developers list venues, search instruments, read an ISIN's listings and issuer, and page through events.

**Blocked by:** None (can start immediately)

**Status:** done

- [x] Tables and migration for markets, issuers, listed_instruments, listing_events
- [x] Ingestion with backfill-safe event rules and ISIN validation; unit tests on synthetic records
- [x] `/v1/markets` endpoints with filters, auth, OpenAPI; integration tests
