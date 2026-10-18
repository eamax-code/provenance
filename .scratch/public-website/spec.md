# Spec: Public website driven by the API

**Status:** implemented 2026-10-18 (tickets 01-03 done) · **Tracker:** local markdown (docs/agents/issue-tracker.md)

## Problem Statement

A visitor to the Provenance website sees marketing copy, an illustrative sample response and a
pricing table typed by hand. Nothing on the page proves the API works or shows what the data
looks like for a real company. A developer evaluating the product has to request a key before
they can see a single filing or fact, and the pricing table can drift from the limits the API
actually enforces.

## Solution

The website becomes a thin client of the same API it sells. Public, keyless, read-only
endpoints expose a bounded showcase of already-ingested companies, the plan limits and the
deployment's coverage. The landing page renders its sample response, pricing and a "live data"
section from those endpoints; a company directory and per-company pages let anyone browse
filings, normalized facts and freshness for the showcase set, every row linking to the SEC
source; a status page shows coverage and the latest quality snapshot. Everything degrades to a
clearly labelled static or empty state when the API is unreachable or the deployment has not
ingested anything yet. Full access, exports, watches and the Explorer still require a key.

## User Stories

1. As a visitor, I want the pricing table to come from the API's plan configuration, so that what I read is what the API enforces.
2. As a visitor, I want the hero's sample response to be a real fact from a real company with a real SEC link, so that I can judge the data shape and provenance before signing up.
3. As a visitor, I want to see which companies this deployment has ingested, with their latest filing and latest annual revenue, so that I know the coverage is real.
4. As a developer evaluating the API, I want to open a public page for a showcase company and see its recent filings with form, date, SEC acceptance time and a link to the SEC index, so that I can compare against EDGAR myself.
5. As a developer, I want the company page to show the five canonical metrics as annual series with units, periods, source tags, accession numbers, quality status and mapping version, so that I can verify normalization against the filing.
6. As a developer, I want each company page to show freshness (last SEC fetch, latest filing detection and processing, null where the SEC gives no timestamp), so that I can see the honesty of the timestamps.
7. As a developer, I want the company page to say plainly when a metric is absent for a company and why that does not mean the issuer has no such value, so that I do not misread gaps.
8. As an AI agent reading the site, I want the public endpoints listed in llms.txt and OpenAPI with no auth, so that I can fetch showcase data without a key.
9. As an operator, I want to choose which companies are public (a configured list, or by default the most recently filed ingested companies up to a cap), so that the public surface is bounded.
10. As an operator, I want public endpoints to never trigger SEC requests, so that anonymous traffic cannot spend my SEC request budget.
11. As an operator, I want public endpoints rate limited per client address and cached for a short interval, so that the site cannot be used to hammer the database.
12. As an operator, I want public responses to contain no customer data, keys, internal errors or secrets, so that exposing them is safe.
13. As a visitor, I want a status page with live coverage counts, health, last ingestion run and the latest quality snapshot, so that I can see whether the service is healthy right now.
14. As a visitor, I want every public page to work on a phone, in light and dark themes, and to be readable without JavaScript for its static parts, so that the site is usable everywhere.
15. As a visitor, I want an empty deployment to say "nothing ingested yet" instead of showing fake numbers, so that I am never misled.
16. As a visitor, I want a failed API call to show a clear "live data unavailable" state, so that a backend outage does not look like missing coverage.
17. As a visitor, I want a company page URL I can share (`/companies/{cik}`), so that a colleague lands on the same company.
18. As a visitor, I want the directory and company pages to link to "get full access" and the Explorer, so that I know how to go further.
19. As a key holder, I want nothing about my keys, watches or usage to appear on public pages, so that my account stays private.
20. As an operator, I want the public endpoints covered by integration tests and the pages covered by served-file and script checks, so that a regression is caught in CI.
21. As a visitor, I want the SEC non-affiliation and data-limitations notice on every public data page, so that I understand what I am looking at.
22. As a developer, I want public JSON to use the same field names and semantics as the authenticated API, so that what I learn on the site transfers to my integration.

## Implementation Decisions

- A new public router under `/v1/public` with three endpoints, none requiring a key:
  `GET /v1/public/plans` (plan names and limits from the plan configuration, with Builder
  flagged as featured), `GET /v1/public/companies` (the showcase list: CIK, name, ticker,
  exchange, latest filing form and date, latest annual revenue value/unit/period with source
  URL, last processed time) and `GET /v1/public/companies/{cik}` (a page bundle: profile,
  the latest ten filings, for each of the five metrics the latest-filed annual observation per
  period for up to the last eight periods, and the freshness summary).
- Showcase membership: the `PUBLIC_SHOWCASE_CIKS` setting (comma-separated) when set;
  otherwise ingested companies ordered by most recent filing date, capped by
  `PUBLIC_SHOWCASE_LIMIT` (default 12). A company outside the showcase, or not yet ingested,
  returns 404 from the public endpoints. Public endpoints never trigger on-demand ingestion.
- Public responses reuse the existing authenticated schemas for filings and facts so field
  names are identical. Facts use the existing "latest-filed preferred observation per period"
  selection; derived values are not included on public pages.
- Public endpoints share the per-IP limiter helper (60 requests per minute per address),
  send `Cache-Control: public, max-age=60`, and are served from an in-process TTL cache keyed
  by endpoint and CIK so repeated page loads do not hit the database. They are marked with
  empty security in OpenAPI and listed in llms.txt.
- Pages: the landing page renders pricing from `/v1/public/plans` (static table remains as
  the no-JS fallback and is replaced when the live data arrives), the hero sample response
  from the first showcase company's latest annual revenue fact, and a "Live data" grid of
  showcase cards. New static pages: `/companies/` (directory) and `/status/`; a server route
  `GET /companies/{cik}` returns the company page HTML so URLs are shareable, with the CIK
  taken from the path by the page script. Pages share one stylesheet and one script with the
  Explorer's visual language; the company page draws the facts chart with the same SVG
  approach as the Explorer.
- Each public data page carries the independence and limitations notice and a "Get full
  access" call to action to the key-request form and the Explorer.
- No new tables. Settings gain `PUBLIC_SHOWCASE_CIKS` and `PUBLIC_SHOWCASE_LIMIT`.

## Testing Decisions

- Seam: the HTTP API through the FastAPI test client, as every existing integration test does
  (tests/integration/test_api_*.py); pages are checked by fetching them through the same
  client and asserting the markup references the public endpoints, and by the CI script
  syntax check for site scripts. No browser automation.
- Good tests assert externally visible behaviour: status codes, response shapes and field
  values from fixture data, absence of secrets and customer fields, rate limit and cache
  behaviour, 404 for non-showcase CIKs, no SEC calls made (the fake SEC transport records
  calls), and the showcase ordering/cap rules.
- Prior art: tests/integration/test_api_stats.py (public endpoint, cache, per-IP limit,
  OpenAPI security), tests/integration/test_api_companies.py (served pages, facts selection).

## Out of Scope

- Public exports, watches, search across the whole universe, or on-demand ingestion from
  public pages.
- Server-side rendering frameworks, a build step, or a JavaScript framework.
- Historical price data or anything beyond SEC filings and facts.
- Authentication for the public pages, analytics, or cookies.

## Further Notes

- Showcase companies are the pilot universe by default, so the public surface grows only
  when the operator ingests more companies.
- Public facts exclude `ambiguous_mapping` and `invalid_source_value` observations from the
  default view, consistent with the authenticated default, and say so in a note.
