# API versioning notes

Changes to the public `/v1` contract, and changes we owe before 1.0 is public. Once 1.0 is out, a
change that breaks a client is a new major version and never an edit to `/v1`.

## Rules in force

- **Unknown query parameters are refused (2026-11-22, ec38f2c).** `/v1/events`,
  `/v1/events/stream`, `/v1/companies/{cik}/facts` and `/v1/facts/screen` answer 422
  `unknown_parameter` with the closest real names and the full list of accepted ones. Before this,
  `/v1/events?type=…` was silently ignored and returned the whole feed. Any new list endpoint that
  filters takes `Depends(strict_query)`.

## Owed before 1.0

- **Align the filter names on `/v1/markets/events`.** It takes `type`, while `/v1/events` takes
  `types` (event kinds) and `event_type` (specific types). Accept `types` there too, keep `type`
  as a documented alias, and add `strict_query` so unknown parameters get the same 422. Update the
  docs page, OpenAPI, MCP tool and Python client together, with a test for the alias and for the
  422. (PM, 2026-11-22.)
