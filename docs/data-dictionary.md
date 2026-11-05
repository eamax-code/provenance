# Data dictionary

All timestamps are UTC (`TIMESTAMPTZ`), serialized as ISO 8601 with a `Z` suffix. Dates are
`YYYY-MM-DD`. Missing values are `null`, never `0`.

These tables describe the stored columns. Some stay internal and are never returned by the API,
the site or the chat: `first_detected_at` and `source_updated_at` on every table, `source_url`
on `companies` (a source API address), and `source_url` on the listing tables (register files
and feeds). Responses link only to documents and filings: a filing's EDGAR index page, and a
company's EDGAR filing list as `filings_url`.

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

## filing_sections

Text read once from a filing and kept, so it can be searched and re-read without the SEC.

| Column | Meaning |
| --- | --- |
| `cik`, `accession_number` | The filing the text came from (join `filings` for form and date) |
| `item` | `pr:*` prospectus sections (`pr:risk`, `pr:use`, …), `5.02` officer changes, `ex:99.1` earnings release |
| `status` | `ok`, `no_section`, `fetch_failed`; only `ok` rows are searched |
| `text` | Plain text, up to 250,000 characters per section |
| `source_url` | The filing's index page on sec.gov |
| `search_vector` | PostgreSQL only: a stored `tsvector` (English) generated from `text`, with a GIN index, used by full-text section search. Not in the ORM model. |

`section_chunks` (PostgreSQL with pgvector only): each searchable section cut into chunks of
about 1,500 characters with 200 of overlap, with `chunk_no`, the chunk `text`, a generated
`search_vector` and one `halfvec` embedding column per model (`embedding_bge` for bge-m3, the
default; `embedding_nomic` for nomic-embed-text), each with an HNSW index. Rows cascade with
their section.

`companies` also has PostgreSQL-only indexes for lookup: a trigram index on `lower(legal_name)`
(typo-tolerant names, `match_type: name_fuzzy`) and one on `upper(ticker)`.

## mart_company, mart_filing_activity (quick answers)

Precomputed by `app/services/marts.py` (`scripts/build_marts.py`; a company's row is refreshed
after it is ingested). Nothing here is new data: every value is copied from `filings` or
`financial_facts` with its accession number and filing link.

| Column | Meaning |
| --- | --- |
| `first_filing_date`, `latest_filing_date`, `filings_last_12_months`, `active` | Filing history among the filings loaded here; active means a filing in the last 12 months |
| `first_registration_date`, `first_registration_form` | First S-1 or F-1 loaded for the company |
| `ipo_prospectus_date`, `_accession`, `_url` | First final prospectus (424B4). With a registration in the two years before it, the chat counts the company as having gone public then |
| `latest_annual_report_date`, `_form` | Latest 10-K, 20-F, 40-F or 10-KT |
| `latest_revenue`, `latest_revenue_period_end` | Latest reported annual revenue in USD (indexed for rankings) |
| `latest_annual` | JSON: the latest annual value of each of the five metrics, with its filing |
| `revenue_history` | JSON: up to five fiscal years of revenue, newest first, each with its filing |

`mart_filing_activity` has one row per month and form type: `filings` and distinct `companies`.

`mart_financials` (ADR 0009): one reported value per `cik`, `metric`, `period_class` (annual or
quarterly), `unit` and `period_end`, the annual report's observation first. Each row also has
`period_start`, `value`, `currency`, the fiscal labels `fiscal_year` and `fiscal_quarter` (from
`app/services/periods.py`, named by the period end and the company's year end), `form_type`,
`filed_date`, `accession_number`, `source_tag`, `source_url`, `quality_status` and
`mapping_version`. Derived quarters are not stored.

`mart_company_period`: one row per `cik` and `fiscal_year`, with `period_end` and the five
annual USD figures as columns, plus `sources` (JSON: each figure's filing link). Exported by
`GET /v1/exports/company-years`.

`company_aliases` (issue #3, step 2): other names a company is found by, one row per `cik`
and `alias`, with `kind` (`former`: a name the SEC lists as the company's former name) and the
dates it was used (`valid_from`, `valid_to`). Ingestion replaces a company's former names from its
submissions; `scripts/load_aliases.py` fills them from the submissions archive without SEC
requests. Company search matches them as `match_type: "former_name"`.

`company_documents` (issue #3): readable documents per company, one row per `cik` and `kind`.
Today the only kind is `profile`: `title` (the company's display name), `markdown` (identity,
latest annual figures, revenue by fiscal year, going public, leadership changes in the last two
years, the risk factor categories of the latest prospectus read here, recent filings; every
figure links to its filing on sec.gov) and `built_at`. On
PostgreSQL a stored `search_vector` (tsvector of title and markdown, GIN-indexed) lets
`GET /v1/search` find companies by the words of their profiles. Rebuilt by
`scripts/build_marts.py` and after each company ingestion.

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

## International listings (ADR 0006)

### markets
One row per covered venue: `mic` (ISO 10383), `operating_mic`, `name`, `country`, `region`
(`canada`, `europe`, `uk`), `source` adapter, `source_url`.

### issuers
`lei` (unique when known), `legal_name`, `country`, `jurisdiction`, `registration_status`
(GLEIF: ISSUED, LAPSED, …), `source` (`gleif` once enriched), `first_detected_at`, `updated_at`.

### listed_instruments
One row per instrument on one venue. `listing_key` is the ISIN when the source provides a
valid one, else `SYM:<symbol>` (Canadian exchange feeds carry no ISIN). Fields: `isin`,
`symbol`, `issuer_name` (instrument full name from FIRDS until GLEIF supplies the legal name),
`issuer_lei`, `short_name`, `cfi_code`, `instrument_type` (`share`, `preferred_share`,
`listing` when the source does not say), `currency`, `admission_requested_date`,
`admission_approved_date`, `first_trade_date`, `termination_date`, `status` (`listed`,
`delisted`, `suspended`), `source`, `source_url` (the register file or feed URL),
`source_record_hash`, `source_published_at`, `first_detected_at`, `last_seen_at`,
`processed_at`, `quality_status` (`partial` when ISIN or first-trade date is missing).

### listing_events
Idempotent per (`listing_key`, `mic`, `event_type`, `event_date`). `event_type` is one of
`new_listing` (first-trade date within 45 days of detection; `details.first_listing_for_issuer_in_our_data`
says whether this service knew other listings of the issuer, which is **not** an IPO
determination), `ipo` (only when a source states it), `delisting` (termination date set or
passed), `suspended`, `reinstated`, `modified` (name or symbol change, with before/after in
`details`). Dates older than the window seen for the first time are backfill and raise nothing.

### market_source_files
Register files already processed per source, so a delta is parsed once; `status` done or
failed with a redacted error.
