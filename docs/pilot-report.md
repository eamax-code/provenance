# Pilot report

The live-week sections below are filled in after the first deployed week (ticket 03). Do not
publish numbers that were not measured. The first section records a full local refresh, which
was measured.

## State on 2026-11-22, 20:00 IST (measured, local)

Mapping 1.4.1, 25.7M facts, 20,615 companies. Every figure below was measured today on the local
database; sources are `docs/data-quality-2026-11-22.md` and `docs/operations.md`.

**Coverage**

| Area | Measure |
| --- | --- |
| Metrics | 34 metrics; periods with an ok figure 98.9-100% for every metric; rows ok under 93% only for cost_of_revenue, d_and_a, interest_expense, revenue, sbc (alternate tags kept for audit) |
| LEI | active USD reporters with $1B+ revenue: 1,605 of 1,898 (84.6%); all active reporters: 4,097 of 7,501 (54.6%) |
| 13F holders | listed companies with $1B+ revenue by USD equivalent (Fed H.10): 1,794 of 1,874 mapped (95.7%), 1,783 with holders in the latest quarter; listed USD reporters $1B+: 1,652 of 1,700 (97.2%). Tonight: 132 wrong issue-number links removed by reviewed rules (preferreds, debt, warrants, cancelled and pre-split CUSIPs, one manager's misfiled 13F), 124 ADR, partnership-unit and exact-name links added; each step hand-checked (final samples 1/30 and 0/30 wrong) |
| Segments | 5,824 companies; 118,632 of 143,366 segment blocks (83%) add up to the consolidated figure or a tagged reconciling item; the rest are shown as unreconciled with the cause |
| First reported (E-2) | 76,428 figures at 1,633 companies matched to the 8-K earnings release that stated them first: 73.6% of those a stored release could have stated (operating cash flow 54.5%, up from 53.6% tonight; most of the rest is not printed in releases) |
| Incorporation | the company's own cover-page state for 7,846 companies, beside the SEC's field (17,925); domestic filers with a US state only, never from combined filings |

**Quality**

- Spot check against the 10-K as filed: 27 of 27 figures match.
- Revenue tag conflicts: 2,239 periods at 452 companies (57,872 at 2,075 before the total-first rule).
- Mapping check: 122 figures at 5 companies stay on an older mapping, all reviewed in `app/data/mapping_exceptions.csv` (rows the SEC's company facts no longer publish); 0 unexpected.
- 39 display names corrected (Novo Nordisk A/S and seven other Danish A/S names; 27 names the SEC data sets glued, such as "NIOInc.").

**Performance** (production image, 2 workers, 50 requests a second for 300 s, all nine endpoints)

| p95 | facts | screen | company overview | ownership | search | stats |
| --- | --- | --- | --- | --- | --- | --- |
| this morning (7 endpoints) | 23.8 ms | 40.1 ms | | | 38.7 ms | 7.0 ms |
| tonight, before fixes | 122.5 ms | 162.3 ms | 76.2 ms | 408.6 ms | 135.4 ms | 38.6 ms |
| tonight, after fixes | 21.7 ms | 37.4 ms | 23.5 ms | 25.6 ms | 40.8 ms | 8.5 ms |

No errors. The first run stalled: requests waited for a second database connection for rate
limits and metering, which now have their own pool; ownership is cached until the next 13F load.
Production smoke: 7 of 8 (readyz flags only the rehearsal settings and the pending email and news
providers).

**At 02:30 IST, mapping 1.5.0** (dry run on the built code; the pass's own counts replace these):
when a filing reports revenue under two tags that disagree, the line on its income statement
decides: 638 published values change at 91 companies and 1,724 ambiguous values get a figure
(Republic Services 2022 $13,511M as on its income statement, not $15,645M). Banks reporting in
IFRS get total income as revenue: 216 values, 55 bank-years at 10 banks (HSBC, UBS, Santander).
Hand-checks: 30 of 30. Every changed value is listed in the quality report; the change is silent
on the event feed.

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
| Time | Archive ingest 32 min; marts 18 min (the new companies ran separately, not timed) |
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

## Production smoke, 2026-11-21 23:31 UTC

Against `http://127.0.0.1:8790` (production settings), `scripts/smoke_prod.py`.

| Check | Result | Time | Detail |
| --- | --- | --- | --- |
| readyz | FAIL | 83 ms | AssertionError: {'status': 'not_ready', 'database': 'ok', 'configuration': ['WEBHOOK_ALLOW_PRIVATE_DESTINATIONS must be false in production', 'EMAIL_PROVIDER=console is for development; use smtp in pr |
| demo key: data and limits | pass | 90 ms | limit 20/min, rows 10 |
| keyed facts with as_of | pass | 45 ms | FY2023 383285000000 filed 2023-11-03 |
| plans | pass | 4 ms | free, analyst, builder, team, enterprise |
| MCP tools/list and a call | pass | 71 ms | 11 tools |
| event stream (SSE) | pass | 13 ms | 2 lines, first retry: 3000 |
| type watch (Builder) | pass | 73 ms | immediate |
| signed webhook to a receiver | pass | 560 ms | delivered and verified (sec.test) |

7 of 8 checks passed.

Notes on this run: the production image (`docker build`, `APP_ENV=production`) ran against the
local database. `readyz` reports two configuration problems, both expected for a rehearsal:
private webhook destinations were allowed so the script's local receiver could be reached
(never in production), and no email provider is configured yet (owner decision O-03). Every
other promise passed. The first run found that the demo key returned 20 rows on endpoints whose
default page is 20; fixed in be39fc6 (at most 10 rows on every list, limit stated in
`X-RateLimit-Limit`).
