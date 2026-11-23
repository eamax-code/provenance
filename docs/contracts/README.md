# API contracts for the 24 Nov window

Status: **contract** (2026-11-24, for provenance-ui). One file per endpoint. A published contract
changes only additively (`docs/api-versioning.md`); a field marked *provisional* may still be
renamed before it is built, and ui is told when it is.

| File | Endpoint | Ticket |
|---|---|---|
| [executive-pay.md](executive-pay.md) | `GET /v1/companies/{cik}/executive-pay` | D-10 |
| [insider-plans.md](insider-plans.md) | `GET /v1/companies/{cik}/insider-plans` | D-11, D-12 |
| [comment-letters.md](comment-letters.md) | `GET /v1/companies/{cik}/comment-letters` | D-13 |
| [corporate-tree.md](corporate-tree.md) | `GET /v1/companies/{cik}/corporate-tree` | D-14 |
| [changes.md](changes.md) | `GET /v1/filings/{accession}/changes`, `GET /v1/companies/{cik}/changes` | X-14 |
| [calendar.md](calendar.md) | `GET /v1/companies/{cik}/calendar`, `GET /v1/watchlists/{id}/calendar` | X-15 |

Common to all, as for the Explorer endpoints (`docs/api-contracts-explorer.md`):
- `X-API-Key` is required. One request is one metered unit. The demo key works on the showcase
  companies only (`403 demo_scope` elsewhere) and gets at most 10 rows on any list.
- Errors use the standard envelope: `404 company_not_found`, `422 invalid_parameter`, and `429`
  with `Retry-After`.
- `as_of` (an ISO date) is accepted wherever it is listed. Only data filed by that date is used,
  with no look-ahead, and the response echoes it (`null` when absent).
- Every value links to its filing: `source_url` is a sec.gov/Archives document or index page.
  Responses never carry a source API URL, `first_detected_at`, `source_updated_at` or a CUSIP.
  GLEIF is named as the source but not linked.
- Derived values say `derived: true` and give their `basis`.
- Insider, plan, Form 144 and pay responses carry
  `labels.disclaimer = "Information, not signals. Not investment advice."`.
- Responses are read from stored data only: nothing is fetched from the SEC on a read.
