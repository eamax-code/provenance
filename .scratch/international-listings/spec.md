# Spec: Canada, Europe and UK public-company identity and listing lifecycle

**Status:** implemented 2026-10-22 (tickets 01-04 done; live FIRDS run pending) · **Tracker:** local markdown · **ADR:** docs/adr/0006

## Problem Statement

Provenance covers US issuers only. A developer or analyst who tracks companies listed in
Canada, the EU/EEA or the UK has no way to learn, from one API, which companies are public on
which venue, when a company first traded, when it was delisted or suspended, or what its legal
identity (LEI) is, with a link back to the official register or exchange record. Existing
sources are scattered across regulator registers and exchange web pages with inconsistent
formats and unclear redistribution terms.

## Solution

A listings domain beside the SEC domain: venues (MIC), issuers (LEI), listed instruments
(ISIN on a venue) and lifecycle events. Official registers (ESMA FIRDS for EU/EEA, FCA FIRDS
for the UK, GLEIF for identity) are ingested on a daily schedule through pluggable source
adapters; exchange-direct lists (TSX/TSXV, CSE, Cboe Canada and selected European exchanges)
add Canadian coverage and explicit IPO/delisting notices where their terms allow. Changes are
detected idempotently and exposed as events. The authenticated API lists venues, searches
instruments, returns an ISIN's listings and issuer, and streams events by type, venue, region
and date. The public site gains a "Listings" view with recent new listings and delistings.
Every row and event names its source and links to the source record; nothing is inferred as
an IPO unless the source says so.

## User Stories

1. As a developer, I want to list the venues the service covers with counts and last-seen times, so that I know the coverage before I integrate.
2. As a developer, I want to search instruments by issuer name, symbol, LEI or ISIN across Canada, Europe and the UK, so that I can resolve a company to its listings.
3. As a developer, I want each listing to carry ISIN, MIC, issuer name, LEI, currency, first-trade and termination dates and status, so that I have a stable identity and lifecycle in one row.
4. As a developer, I want all listings of one ISIN across venues plus the issuer record, so that I see dual listings at a glance.
5. As an analyst, I want a feed of new listings for a region or venue since a date, so that I can spot companies that just went public.
6. As an analyst, I want a feed of delistings and suspensions, so that I can retire companies from my watch list.
7. As an analyst, I want name and symbol changes surfaced as events, so that my mappings stay current.
8. As an analyst, I want IPO events only where an exchange states an IPO, and new-listing events otherwise, so that I am never told a secondary line is an IPO.
9. As a developer, I want each event to carry the source, the source URL, the event date from the source and the time the service detected it, so that I can audit it.
10. As a developer, I want the first ingestion of a venue to backfill without raising thousands of events, so that my webhook is not flooded.
11. As a developer, I want issuer identity from GLEIF (legal name, country, registration status) attached by LEI, so that identity is authoritative and cross-border.
12. As an operator, I want each source adapter switchable by configuration with its terms documented, so that I can disable a source whose terms I cannot accept.
13. As an operator, I want daily ingestion to be bounded (delta files, configured venues) and resumable, so that it fits the budget and recovers from failures.
14. As an operator, I want ingestion runs and quality snapshots to include listings counts and event counts, so that I can monitor the new domain like the old one.
15. As an AI agent, I want the listings endpoints in OpenAPI and llms.txt with the event vocabulary, so that I can call them without guessing.
16. As a visitor, I want a public page of recent new listings and delistings for the showcase venues, so that I can see the feature works before requesting a key.
17. As a developer, I want ISINs validated and normalized, so that bad identifiers are rejected early.
18. As an operator, I want unit tests on fixtures for every parser and integration tests on the API, so that regressions are caught in CI without network access.
19. As a key holder, I want to watch a venue or region for new listings and delistings by webhook, so that I am notified without polling (follow-up, not in this spec).
20. As a visitor, I want the data-rights page to state each source's terms and attribution, so that I understand what I may redistribute.

## Implementation Decisions

- Domain tables: `markets` (MIC, operating MIC, name, country, region, source), `issuers`
  (LEI unique, legal name, country, jurisdiction, registration status, source), `listed_instruments`
  (unique per ISIN+MIC, with dates, status, source, record hash, first/last seen) and
  `listing_events` (idempotent key over ISIN, MIC, type, date; JSON details).
- A source-agnostic `ListingRecord` is the contract between adapters and ingestion. Ingestion
  upserts by (ISIN, MIC), keeps `first_detected_at`, and raises events: `new_listing` for a
  first-trade date within a window of today, `delisting` when a termination date appears or
  passes, `suspended`/`reinstated` on explicit status changes, `modified` on name or symbol
  changes, and `ipo` only when the record carries an explicit source statement. Old dates seen
  for the first time are backfill and raise nothing.
- Adapters (one module each, enabled by settings): ESMA FIRDS delta files (equity CFI codes,
  configured MICs), FCA FIRDS (same schema, UK venues), GLEIF LEI lookups by LEI and ISIN
  for issuer enrichment, and Canadian exchange adapters chosen after the research pass
  (identity and lifecycle metadata only, terms permitting). Each adapter records the file or
  page it read as `source_url`.
- Venue registry: a versioned list of covered MICs with name, country and region, seeded
  from configuration; FIRDS records for venues outside the list are ignored.
- API under `/v1/markets` (key required): venues, instruments with filters and search,
  instrument detail by ISIN, events with filters, issuer by LEI. Public: recent events for
  showcase venues on the site via the existing public cache pattern.
- Jobs: `scripts/ingest_markets.py --source <name> [--date]` and a daily step in the poller
  guarded by the same single-run lock; run counts flow into `ingestion_runs` and the quality
  snapshot gains listing/event counts.
- Documentation: data-rights entries per source with quoted terms; data dictionary; README;
  llms.txt; a research report in docs/research with the verified sources and the reasons
  for each inclusion or exclusion.

## Testing Decisions

- Seam: the HTTP API through the test client for behaviour, and the adapter parse functions
  on fixture files (real sample records captured during research, trimmed) for formats. No
  network in tests; live fetches are opt-in by environment variable like the SEC smoke test.
- Good tests assert visible behaviour: rows and events produced from a fixture, idempotency
  on re-ingestion, event windows, ISIN validation, API filters and auth, OpenAPI coverage.
- Prior art: tests/unit/test_ingestion.py, tests/unit/test_universe.py,
  tests/integration/test_api_public.py.

## Out of Scope

- Prices, market data, index membership, corporate actions beyond listing lifecycle.
- Financial statements for non-US issuers (ESEF/XBRL) and filings search for Canada/Europe.
- Webhook watches on venues (follow-up ticket once the feed is stable).
- Asia-Pacific and other regions.

## Further Notes

- FIRDS reference data is instrument-level; "company went public" must be read as "an equity
  instrument of this issuer first became tradable on a covered venue", which the API states.
- Exchange terms differ; the research report is the source of truth for what each adapter
  may do, and adapters default to disabled until the operator accepts the terms.
