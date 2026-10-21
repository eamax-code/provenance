# Data sources, rights, attribution and limitations

This document is a product requirement. It is **not** a legal opinion, and no legal review
has been completed yet.

## Sources used (all SEC-hosted)

| Purpose | URL |
| --- | --- |
| Company identity, filings index | `https://data.sec.gov/submissions/CIK##########.json` |
| XBRL company facts | `https://data.sec.gov/api/xbrl/companyfacts/CIK##########.json` |
| Ticker/exchange association | `https://www.sec.gov/files/company_tickers_exchange.json` |
| Human-readable filing index (linked as `source_url`) | `https://www.sec.gov/Archives/edgar/data/{cik}/{accession}/{accession}-index.html` |

Access follows the SEC fair-access guidance: a descriptive `User-Agent` with a monitored
contact address, at most 4 requests/second by default, conditional requests (ETag /
Last-Modified), exponential backoff honoring `Retry-After`, and no attempt to bypass throttling.
Confirm the current guidance at https://www.sec.gov/os/accessing-edgar-data before deploying.

## International listing sources (Canada, Europe, UK)

Added 2026-10-22 (ADR 0006). Identity and listing lifecycle only; no financial statements.

| Source | Terms (quoted) | Our use |
| --- | --- | --- |
| ESMA FIRDS, `https://registers.esma.europa.eu/` and `https://firds.esma.europa.eu/firds/` | "Reproduction of all information on this site (ESMA Library) is authorised except as otherwise stated" provided "the source is acknowledged"; must not "imply that ESMA is endorsing a firm" | Daily delta files for covered EU/EEA venues; source acknowledged on every row |
| FCA FIRDS, `https://data.fca.org.uk/` | "The FCA owns the copyright … in all material on this site"; datasets in the Data section under the UK Open Government Licence; no FIRDS-specific licence found | Daily delta files for UK venues only; FCA acknowledged; identity metadata only |
| GLEIF, `https://api.gleif.org/` | "The data available through the Access Service are provided under the CC0 licence"; no suggestion of GLEIF endorsement | Issuer legal identity by LEI |
| TSX / TSXV, `https://www.tsx.com/json/company-directory/` | Licence "to view and print the material … for your non-commercial or personal use only"; "you may not use, distribute, sell, modify … information, data … without TMX's prior written permission" | Adapter shipped **disabled**; enable only with written permission from TMX |
| CSE, `https://thecse.com/api/webapi/listed-companies/` | "You may not … copy, reproduce, republish … distribute … for any purpose other than personal, non-commercial use, without prior written consent from the CSE" | Adapter shipped **disabled**; enable only with written consent |
| SEDAR+, Cboe Canada, LSE, Euronext, SIX, Nasdaq Nordic | Automated access and/or redistribution prohibited without licence | Not used |

Attribution shown on listing endpoints and pages: "Listing data from ESMA FIRDS, FCA FIRDS and
GLEIF; Provenance is independent and not affiliated with ESMA, the FCA, GLEIF, the CSA, TMX,
the CSE or any exchange."

## Intended use

Make official filing information easier to discover, normalize, monitor and consume through a
documented API. Every filing and every normalized fact links back to its SEC source.

## Explicitly excluded

- Stock quotes, EOD/intraday prices, OHLCV, order books, corporate-action adjustments.
- Analyst estimates, consensus, news, transcripts, vendor-enriched datasets.
- Investment advice, valuation models, buy/sell signals.
- Financial statements for non-US issuers; custom company XBRL extensions. (Non-US listing identity and lifecycle are in scope since ADR 0006.)
- Unbounded bulk mirrors or unlimited exports.

No paid or third-party dataset is used or redistributed. The exchange field comes from the SEC
ticker file, not from exchange market data.

## Attribution and independence

Data is sourced from the U.S. Securities and Exchange Commission's EDGAR system. This service
is independent and is **not affiliated with, endorsed by, or sponsored by the SEC**. Every API
response that carries data includes an SEC `source_url`; exports include an `X-Data-Source`
header and a `source_url` column.

## Limitations notice (shown in `/docs`)

- SEC source updates, filing availability, taxonomy coverage and timestamps vary. A missing
  field means the SEC endpoint did not expose it, not that the issuer has no such information.
- Only the `recent` block of the submissions feed is ingested (roughly the latest 1,000
  filings per company). Older filings referenced via `filings.files` are not loaded in the MVP.
- Facts come from the SEC company-facts API and standard `us-gaap` tags only.
- `accepted_at` is the SEC acceptance timestamp; no dissemination timestamp exists in the source,
  so `source_published_at` is always `null` and `publication_to_detection_seconds` is never
  computed.
- Values marked `derived=true` are computed by this service, not reported by the issuer.
- Nothing here is audited, verified or complete beyond what the SEC publishes. Review the
  underlying filing before relying on a value.

## Retention policy (documented defaults)

- `api_usage`: retain 90 days (`USAGE_RETENTION_DAYS`), then purge.
- `notification_deliveries`: retain 90 days after final status (`DELIVERY_RETENTION_DAYS`).
- Exports are streamed and never stored server side.
- SEC response cache (`.sec_cache`) holds only public SEC payloads and may be deleted at any time.
- Purge jobs are not yet automated; see docs/operations.md.

## Open legal questions before selling bulk access

1. Confirm the current SEC terms and fair-access policy permit the planned commercial packaging.
2. Confirm redistribution conditions for derived datasets and the required attribution text.
3. Customer contract terms: no SLA on freshness, no warranty of completeness, no investment advice.
4. Review any future third-party data before inclusion; none is included today.
