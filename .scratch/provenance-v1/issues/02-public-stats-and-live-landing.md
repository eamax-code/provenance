# 02: Public stats endpoint and a live landing page

**What to build:** A visitor to the landing page sees real coverage numbers (companies, filings, facts, last successful SEC fetch, ingestion health) fetched from an unauthenticated, cached `/v1/stats` endpoint instead of static marketing figures. The page states clearly when the service has not ingested anything yet.

**Blocked by:** 01

**Status:** ready-for-agent

- [ ] `GET /v1/stats` needs no API key, is rate limited per IP, cached for a short interval, and exposes no secrets or internals
- [ ] Stats include company/filing/fact counts, last successful fetch time, last ingestion run status, share of facts by quality status, pending delivery backlog
- [ ] Landing page hero strip and a status section render from `/v1/stats`, with an honest empty state and a failure state
- [ ] Integration tests cover the endpoint shape, caching and rate limiting; the site test asserts the live wiring
