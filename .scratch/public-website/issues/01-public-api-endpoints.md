# 01: Public showcase API (plans, companies, company bundle)

**What to build:** Anyone can fetch, without a key, the plan limits, the showcase company list and a per-company bundle (profile, latest filings, annual facts, freshness) for companies this deployment has ingested, within per-IP limits and a short cache, never triggering SEC requests.

**Blocked by:** None (can start immediately)

**Status:** done

- [x] `GET /v1/public/plans`, `GET /v1/public/companies`, `GET /v1/public/companies/{cik}` exist, need no key, are rate limited per IP, cached 60 s, and marked public in OpenAPI and llms.txt
- [x] Showcase = `PUBLIC_SHOWCASE_CIKS` or the most recently filed ingested companies up to `PUBLIC_SHOWCASE_LIMIT`; others return 404; no SEC call is made
- [x] Responses reuse the authenticated field names; no secrets, keys, usage or watch data
- [x] Integration tests cover shape, ordering, cap, 404, cache, rate limit, no-SEC-call
