# provenance-client

Python client for the Provenance API: US companies and SEC filings, normalized facts with
point-in-time queries, Canada/EU/UK listing events, and the live event feed. Depends on `httpx`
only; `pandas` is optional.

```bash
pip install "provenance-client[pandas] @ git+https://github.com/eamax-code/provenance#subdirectory=clients/python"
```

```python
from provenance_client import Client, to_dataframe

client = Client(api_key="YOUR_KEY", base_url="https://YOUR-DEPLOYMENT")
# or set PROVENANCE_API_KEY and PROVENANCE_BASE_URL; without a key the public "demo" key is used

client.search("AAPL")
facts = client.facts("320193", metric="revenue")                     # latest values
known = client.facts("320193", metric="revenue", as_of="2024-01-15")  # what was filed by then
to_dataframe(known)[["period_end", "value", "filed_date", "accession_number"]]

client.screen("total_assets", 2024, as_of="2025-03-31")              # ranking as of a date
list(client.filings("320193", form_type="8-K", max_rows=10))
list(client.listing_events(type="new_listing", region="uk", max_rows=20))
```

## Event feed

New SEC filings and listing events in one ordered feed. Store `client.last_cursor` to resume
exactly where you stopped.

```python
for event in client.events(since="2026-11-01T00:00:00Z"):   # catch up, then return
    print(event["type"], event["data"])
cursor = client.last_cursor

for event in client.stream(after=cursor, types="filing", form_type="8-K"):  # live (SSE)
    print(event["data"]["company_name"], event["data"]["source_url"])
```

`stream()` reconnects with `Last-Event-ID` after network errors and when the server closes a
long-lived connection, so no event is skipped or repeated. `events(follow=True)` does the same
by polling, for environments that block streaming responses.

## Errors

API errors raise `ProvenanceError` with `status`, `code` (stable, e.g. `invalid_api_key`,
`rate_limited`), `message` and `request_id`. 429 and 5xx responses are retried using
`Retry-After` (up to `max_retries`, default 2).
