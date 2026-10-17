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

## Intended use

Make official filing information easier to discover, normalize, monitor and consume through a
documented API. Every filing and every normalized fact links back to its SEC source.

## Explicitly excluded

- Stock quotes, EOD/intraday prices, OHLCV, order books, corporate-action adjustments.
- Analyst estimates, consensus, news, transcripts, vendor-enriched datasets.
- Investment advice, valuation models, buy/sell signals.
- Non-US issuers beyond what appears in SEC filings; custom company XBRL extensions.
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
