# Pilot report

The live-week sections below are filled in after the first deployed week (ticket 03). Do not
publish numbers that were not measured. The first section records a full local refresh, which
was measured.

## Local full refresh, 2026-11-15 (measured)

Run on the owner's machine against Docker PostgreSQL, from the SEC's nightly archives
(`scripts/sec_bulk.py --download`, then `--scope facts`, then the 998 companies without XBRL),
with the SEC contact address in the User-Agent.

| Measure | Result |
| --- | --- |
| SEC requests | 3: two archive downloads (`submissions.zip` 1.57 GB, `companyfacts.zip` 1.43 GB) and the ticker file |
| Companies | 21,586 known and ingested (1,011 new from the ticker file); 0 with fetch errors; 0 failed |
| New since 2026-11-03 | 120,057 filings and 50,168 facts |
| Totals | 8,854,164 filings (all with an SEC acceptance time) and 5,630,256 facts |
| Time | Archive ingest 32 min; marts 18 min; new companies about 15 min |
| Facts by quality | ok 95.42%, ambiguous_mapping 3.99%, partial 0.59%, invalid_source_value 0 |
| Duplicate filings | 0 |
| Facts with full provenance | 100% |
| SEC acceptance to here, filings first seen in 24 h | median 24.1 h, 95th percentile 44.6 h (nightly archive only; the poller is not running locally) |
| Live SEC smoke test | `SEC_LIVE_TESTS=1 pytest tests/integration/test_live_sec_smoke.py`: passed |
| Listings | ESMA, FCA and GLEIF refreshed for 10 days: 38 venues, 4,869 instruments |

Issues found and fixed in the same session:
1. `fiscal_year` on facts is the SEC label of the filing, so a 10-K's comparative for last year
   carried this year's label (Apple's FY2025 revenue showed as 2026). Added `period_fiscal_year`
   and `period_label`.
2. Detection-to-processing latency counted old filings re-processed by the bulk load (median
   11 days). It now counts new arrivals only, and the snapshot adds acceptance-to-detection.
3. Without `PUBLIC_SHOWCASE_CIKS`, production would feature whichever companies filed last; the
   deploy files now list twelve.

Open: GDELT can be slow (one 10-second timeout in testing), and about 4% of facts are
`ambiguous_mapping`. Both are shown honestly in the API.


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
