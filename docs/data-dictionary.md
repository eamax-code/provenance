# Data dictionary

All timestamps are UTC (`TIMESTAMPTZ`), serialized as ISO 8601 with a `Z` suffix. Dates are
`YYYY-MM-DD`. Missing values are `null`, never `0`.

## Quality statuses (controlled vocabulary)

| Status | Meaning |
| --- | --- |
| `ok` | Required fields present and mapping unambiguous |
| `partial` | One or more optional fields/timestamps unavailable in the SEC source |
| `ambiguous_mapping` | Several candidate XBRL tags cover the period, or they disagree, or the source period type did not match the metric |
| `invalid_source_value` | The SEC value could not be parsed as a number; `value` is `null` |
| `stale` | Last successful SEC fetch is older than `FRESHNESS_STALE_AFTER_SECONDS` (freshness endpoint only) |
| `unavailable` | Source endpoint or requested fact not available |
| `derived` | Value computed by this service from two reported observations (`derived=true`, `derivation` present) |

## companies

| Column | Meaning |
| --- | --- |
| `cik` | 10-digit zero-padded SEC Central Index Key. Canonical identifier. |
| `legal_name` | Name from SEC submissions (or the ticker file before first ingestion) |
| `ticker`, `exchange` | Current primary ticker/exchange as listed by the SEC. Not a permanent identity. |
| `sic_code`, `sic_description`, `entity_type`, `state_of_incorporation`, `fiscal_year_end` | As reported in SEC submissions |
| `source_url` | SEC submissions URL (or ticker file URL before ingestion) |
| `source_updated_at` | `Last-Modified` header of the submissions response, when the SEC sends one |
| `first_detected_at` | First time this service saw the company |
| `last_processed_at` | Last completed ingestion |
| `last_successful_fetch_at` | Last successful SEC fetch (drives `stale`) |
| `last_fetch_error_at`, `last_fetch_error` | Most recent failed attempt (redacted message). Data shown is from the last success. |
| `quality_status` | `ok` when filings and facts both ingested; `partial` otherwise |

## filings

| Column | Meaning |
| --- | --- |
| `accession_number` | SEC accession number `##########-##-######`; unique per CIK |
| `form_type` | SEC form (`10-K`, `10-Q`, `8-K`, ...). `UNKNOWN` if missing in source. |
| `filing_date` | Date-only filing date from SEC |
| `report_date` | Period of report, when given |
| `accepted_at` | SEC `acceptanceDateTime` when present. Never inferred from `filing_date`. |
| `source_published_at` | Always `null`: the SEC submissions feed has no public-dissemination timestamp. Kept for schema stability. |
| `primary_document` | Primary document file name |
| `source_url` | `https://www.sec.gov/Archives/edgar/data/{cik}/{accession-no-dashes}/{accession}-index.html` |
| `source_payload_hash` | SHA-256 of the normalized source fields; unchanged payload = no update |
| `first_detected_at` | When this service first saw the accession number (preserved across re-ingestion) |
| `processed_at` | Last time the row was written |
| `ingestion_run_id` | Run that last touched the row |
| `quality_status` | `ok` or `partial` (e.g. acceptance timestamp missing) |

## financial_facts

One row per **source observation**: metric x tag x unit x period x accession. Restated values
from later filings are additional rows, never overwrites.

| Column | Meaning |
| --- | --- |
| `metric` | `revenue`, `operating_income`, `net_income`, `total_assets`, `operating_cash_flow` |
| `value` | Numeric as reported (sign preserved). `null` if unparseable. |
| `unit` | XBRL unit (`USD`, `shares`, ...) |
| `currency` | ISO code when the unit is a plain currency; otherwise `null` |
| `period_start`, `period_end` | Duration bounds; `period_start` is `null` for instants |
| `period_type` | `duration` or `instant` |
| `period_class` | `annual` (350-380 days), `quarterly` (80-100 days), `ytd` (160-290 days), `other`. For instants: by form (`10-K`=annual, `10-Q`=quarterly). Derived from the reported dates, **not** from the SEC `fp` label. |
| `fiscal_year`, `fiscal_period` | SEC `fy`/`fp` of the *filing* that reported the value (a 6-month YTD value carries `fp=Q2`) |
| `form_type`, `filed_date`, `accession_number` | Filing that reported the observation |
| `source_tag`, `source_taxonomy` | XBRL concept and taxonomy (`us-gaap`) |
| `source_url` | Filing index URL of the reporting filing |
| `mapping_version` | Version of the concept mapping (`1.0.0`) |
| `quality_status` | See table above |
| `derived`, `derivation` | Derived quarter values are only produced at query time (`include_derived=true`) and are not stored |
| `observation_key` | SHA-256 over metric, taxonomy, tag, unit, period, accession, derived flag; unique |
| `first_detected_at`, `processed_at` | Provenance timestamps |

### Concept mapping v1.0.0

| Metric | Candidate tags, in precedence order | Period |
| --- | --- | --- |
| `revenue` | `RevenueFromContractWithCustomerExcludingAssessedTax`, `Revenues`, `SalesRevenueNet`, `RevenueFromContractWithCustomerIncludingAssessedTax` | duration |
| `operating_income` | `OperatingIncomeLoss` | duration |
| `net_income` | `NetIncomeLoss` only (parent/common-shareholder variants are not substituted) | duration |
| `total_assets` | `Assets` | instant |
| `operating_cash_flow` | `NetCashProvidedByUsedInOperatingActivities` | duration |

Precedence rule: for each (unit, period), the first tag in the list that has observations is
*preferred*. Preferred observations are `ok`; alternates are `ambiguous_mapping`. If the
latest-filed values of two tags disagree, the preferred one is also `ambiguous_mapping`.

API default view: one row per (metric, unit, period), the latest-filed `ok`/`partial`
observation. `revision_count` is the number of stored observations of that tag for the period;
`include_all_observations=true` returns them all.

## ingestion_runs

Counts and status (`running`, `succeeded`, `partial`, `failed`) per ingestion pass, with a
redacted `error_summary`.

## api_keys, api_usage, audit_events

Keys store a prefix and a peppered SHA-256 hash only. `api_usage` has one row per
authenticated request with `route_template`, status, `response_bytes`, and `export_rows` for
exports. `audit_events` records key creation/revocation and watch changes.

## company_watches, notification_deliveries

A watch binds an API key to a CIK and a destination. Webhook secrets are derived from
`WEBHOOK_SIGNING_SECRET` and the watch id (only the hash is stored). Deliveries have a stable
`event_id` (`evt_` + hash of watch, CIK, accession) and a status of `pending`, `retrying`,
`delivered` or `failed`.
