# API versioning notes

Changes to the public `/v1` contract, and changes we owe before 1.0 is public. Once 1.0 is out, a
change that breaks a client is a new major version and never an edit to `/v1`.

## Rules in force

- **Unknown query parameters are refused (2026-11-22, ec38f2c).** `/v1/events`,
  `/v1/events/stream`, `/v1/companies/{cik}/facts` and `/v1/facts/screen` answer 422
  `unknown_parameter` with the closest real names and the full list of accepted ones. Before this,
  `/v1/events?type=…` was silently ignored and returned the whole feed. Any new list endpoint that
  filters takes `Depends(strict_query)`.
- **`/v1/markets/events` takes `types` (2026-11-22).** A comma-separated list of listing event
  types, matching the feed's plural name. `type` stays as a documented alias and may be combined
  with `types`; existing calls such as `?type=new_listing` keep working. Unknown parameters get the
  same 422 `unknown_parameter`, and an unknown event type gets 422 `invalid_parameter`. The MCP
  tool `listing_events` takes `types`; the Python client passes either through.

## Owed before 1.0

Nothing open.
