# 18: Python client

**What to build:** A small `provenance-client` package (httpx only; pandas optional) in `clients/python/`. A notebook user gets companies, filings, point-in-time facts, the screen and listing events as dicts or DataFrames. They can also follow the live event stream, with automatic reconnect from the last event id.

**Blocked by:** 16, 17

**Status:** in-progress

- [ ] `Client(api_key, base_url)`; typed errors that carry the API error code and request id; respects `Retry-After` on 429
- [ ] Pagination helpers; `facts(..., as_of=)`; `to_dataframe()` when pandas is installed
- [ ] `events()` polling iterator and `stream()` SSE iterator that resume from the last id
- [ ] Tests run against the real app through an httpx transport; README snippet; site docs link
