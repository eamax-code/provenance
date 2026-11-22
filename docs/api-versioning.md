# API versioning notes

Changes to the public `/v1` contract, and changes we owe before 1.0 is public. Once 1.0 is out, a
change that breaks a client is a new major version and never an edit to `/v1`.

## Rules in force

- **Unknown query parameters are refused (2026-11-22, ec38f2c).** `/v1/events`,
  `/v1/events/stream`, `/v1/companies/{cik}/facts` and `/v1/facts/screen` answer 422
  `unknown_parameter` with the closest real names and the full list of accepted ones. Before this,
  `/v1/events?type=…` was silently ignored and returned the whole feed. Any new list endpoint that
  filters takes `Depends(strict_query)`.
- **One meaning per parameter name (2026-11-22).** On both feeds `event_type` holds specific
  event types (`new_listing`, `sec.restatement`, …), comma-separated, and `types` holds kinds only
  (`filing`, `listing`, `insider`, `calendar`, `leadership`), on `/v1/events`.
  `/v1/markets/events` takes `event_type`; an unknown event type gets 422 `invalid_parameter` and
  an unknown parameter 422 `unknown_parameter`. The MCP tool `listing_events` takes `event_type`.

## Deprecated, removed at 1.0

- **`type` and `types` on `/v1/markets/events`.** Both are aliases of `event_type` there, marked
  `deprecated` in OpenAPI, and may be combined with it. They are removed when 1.0 is public, after
  which they get 422 `unknown_parameter` like any other unknown name.

## Owed before 1.0

- Remove the two deprecated aliases above.
