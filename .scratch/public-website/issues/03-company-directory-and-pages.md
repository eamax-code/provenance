# 03: Company directory, public company pages and status page

**What to build:** A visitor browses `/companies/`, opens `/companies/{cik}` to see filings, the five metrics as annual series with chart and provenance table, and freshness, and opens `/status/` to see live coverage and the latest quality snapshot. Every page has the notice and a "Get full access" call to action.

**Blocked by:** 01

**Status:** done

- [x] `/companies/` and `/status/` static pages; `GET /companies/{cik}` returns the company page HTML
- [x] Company page renders filings, facts (chart + table with source links, absent-metric explanation), freshness, from the bundle endpoint; 404 and offline states are explicit
- [x] Status page renders `/v1/stats` including the quality snapshot
- [x] Phone width, both themes, notice and CTA on each page; served-page tests and script checks
