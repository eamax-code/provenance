# provenance-client changelog

The client's version follows the API version it was released with (`app_version`).

## 0.1.0 (2026-11-15)

- `Client` with search, companies, filings, facts (with `as_of`), screen, listing events, the
  event feed (`events`, `events(follow=True)`) and the live stream (`stream`) with resume.
- `ProvenanceError` with stable `code`, `status`, `message` and `request_id`; 429 and 5xx are
  retried using `Retry-After`.
- `to_dataframe` for pandas (optional extra).
- Sends `User-Agent: provenance-client/<version>`.
