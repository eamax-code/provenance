# Pilot report (template, no measurements yet)

Fill this in after the first live week. Do not publish numbers that were not measured.

## Setup
- Deployment: (host, region, deploy date)
- SEC_USER_AGENT contact: (monitored mailbox, no placeholder)
- Universe: (N companies, source, seed date)
- Poll interval: 300 s; universe refresh: 6 h; history pages: 0

## Live smoke test
- `SEC_LIVE_TESTS=1 pytest tests/integration/test_live_sec_smoke.py`: (date, result)

## Freshness (from `data_quality_snapshots` and `filings`)
- acceptance_to_detection_seconds for filings detected after the watch existed: p50 / p90 / max
- companies_stale over the week: max, how long
- SEC requests per day, retries, errors (from `ingestion_runs`)

## Data quality
- facts_total, share ok / partial / ambiguous_mapping / invalid_source_value
- duplicate_filings (expected 0)
- facts_with_provenance_pct (expected 100)
- Companies where a canonical metric is absent, with the reason found in the filing

## Notifications
- deliveries attempted / delivered / failed; retry counts; oldest pending

## Issues found, by severity
1.
