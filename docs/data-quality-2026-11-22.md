# Data quality, mapping 1.4.1 (2026-11-22)

## Per metric

Periods with an ok figure: for each company and period, is there an ok figure (what a user meets). Rows ok counts stored rows: when a filing reports a figure under two tags, the alternate one is kept and marked ambiguous, never deleted, which is why the row % is lower for sbc, d_and_a and revenue.

| Metric | Periods with an ok figure | Rows ok (alternate tags kept for audit) | % ambiguous | % suspicious period | Facts | Companies (ok) | Earliest ok year |
|---|---|---|---|---|---|---|---|
| capex | 100.0% | 96.7% | 2.8 | 0.00 | 663,256 | 12,348 | 2005 |
| cash_and_equivalents | 100.0% | 99.6% | 0.0 | 0.02 | 1,182,729 | 15,782 | 1993 |
| cost_of_revenue | 99.2% | 91.5% | 8.0 | 0.00 | 678,007 | 9,066 | 2003 |
| current_assets | 100.0% | 99.5% | 0.0 | 0.00 | 679,649 | 14,110 | 2001 |
| current_liabilities | 100.0% | 99.5% | 0.0 | 0.00 | 679,288 | 14,061 | 2001 |
| d_and_a | 100.0% | 87.4% | 12.2 | 0.00 | 778,196 | 11,006 | 2003 |
| dividends_paid | 98.9% | 96.0% | 3.6 | 0.00 | 301,559 | 5,269 | 2001 |
| eps_basic | 99.9% | 94.8% | 4.8 | 0.00 | 1,413,803 | 15,172 | 1997 |
| eps_diluted | 99.9% | 95.2% | 4.4 | 0.00 | 1,378,620 | 14,948 | 1997 |
| gross_profit | 100.0% | 99.5% | 0.0 | 0.00 | 610,286 | 7,889 | 1997 |
| income_tax | 100.0% | 99.6% | 0.0 | 0.00 | 1,000,083 | 13,521 | 2001 |
| interest_expense | 99.8% | 92.9% | 6.7 | 0.00 | 939,162 | 12,904 | 1999 |
| long_term_debt | 100.0% | 93.5% | 6.0 | 0.00 | 307,334 | 6,798 | 2003 |
| long_term_debt_current | 100.0% | 99.5% | 0.0 | 0.01 | 178,559 | 5,560 | 2007 |
| net_income | 100.0% | 99.0% | 0.0 | 0.01 | 1,607,660 | 16,370 | 1993 |
| net_interest_income | 100.0% | 99.7% | 0.0 | 0.00 | 243,515 | 3,904 | 2007 |
| operating_cash_flow | 100.0% | 99.5% | 0.0 | 0.00 | 810,151 | 16,616 | 1999 |
| operating_income | 100.0% | 99.5% | 0.0 | 0.00 | 1,148,168 | 13,907 | 2003 |
| pretax_income | 100.0% | 94.1% | 5.5 | 0.00 | 1,063,958 | 13,178 | 2003 |
| public_float | 100.0% | 100.0% | 0.0 | 0.01 | 117,628 | 14,311 | 2000 |
| r_and_d | 100.0% | 98.9% | 0.6 | 0.00 | 426,683 | 6,224 | 2003 |
| retained_earnings | 100.0% | 99.5% | 0.0 | 0.00 | 788,016 | 15,650 | 1994 |
| revenue | 99.6% | 89.6% | 10.0 | 0.00 | 1,290,299 | 13,271 | 2003 |
| sbc | 99.9% | 75.2% | 24.4 | 0.00 | 1,050,353 | 12,592 | 1995 |
| sga | 100.0% | 99.6% | 0.0 | 0.00 | 443,398 | 5,492 | 2003 |
| share_repurchases | 99.9% | 99.4% | 0.2 | 0.00 | 281,609 | 6,995 | 1999 |
| shares_basic_weighted | 100.0% | 94.8% | 4.8 | 0.00 | 1,208,125 | 14,787 | 2003 |
| shares_diluted_weighted | 100.0% | 95.2% | 4.3 | 0.00 | 1,161,776 | 14,302 | 2003 |
| shares_outstanding | 100.0% | 100.0% | 0.0 | 0.00 | 385,484 | 15,264 | 2001 |
| stockholders_equity | 100.0% | 99.6% | 0.0 | 0.01 | 1,273,067 | 15,877 | 1993 |
| total_assets | 100.0% | 99.5% | 0.0 | 0.00 | 885,545 | 16,968 | 2001 |
| total_liabilities | 100.0% | 99.5% | 0.0 | 0.00 | 700,026 | 15,083 | 2003 |

Metrics under 93% ok by row: cost_of_revenue, d_and_a, interest_expense, revenue, sbc. Their periods with an ok figure: cost_of_revenue 99.2%, d_and_a 100.0%, interest_expense 99.8%, revenue 99.6%, sbc 99.9%. The rest are alternate tags in the same filing (for example AllocatedShareBasedCompensationExpense beside ShareBasedCompensation).

Facts on an older mapping: 122 rows at 5 companies (observations the SEC's company facts no longer publish, so no pass can re-read them; kept as reported, on the mapping that read them; listed by scripts/check_mapping.py).

## Revenue tag conflicts

Revenue periods where the tags one filing reports disagree: 57,872 periods at 2,075 companies before the total-first rule, 2,239 at 452 now.

## Large filers whose revenue stopped

Values are compared as reported, without exchange rates, so the $1B threshold applies to USD reporters only; other reporting currencies are listed without a threshold.

- USD reporters with $1B+ revenue at some point, an annual report in the last two years, but no annual revenue mapped in the last three years: 41.
- Non-USD reporters (any size) in the same position: 23.

- — DOW CHEMICAL CO /DE/: last 2018-12-31, peak $60.3B
- CTA-PB EIDP, Inc.: last 2016-12-31, peak $38.0B
- UBS UBS Group AG: last 2021-12-31, peak $35.4B
- FRFHF FAIRFAX FINANCIAL HOLDINGS LTD/ CAN: last 2022-12-31, peak $28.1B
- — BURLINGTON NORTHERN SANTA FE, LLC: last 2022-12-31, peak $25.9B
- — XEROX CORP: last 2018-12-31, peak $22.6B
- WMB WILLIAMS COMPANIES, INC.: last 2020-12-31, peak $11.9B
- — TOYOTA MOTOR CREDIT CORP: last 2017-03-31, peak $11.2B
- — HERTZ CORP: last 2015-12-31, peak $11.0B
- — KENTUCKY UTILITIES CO: last 2015-12-31, peak $7.9B
- — PEPCO HOLDINGS LLC: last 2015-12-31, peak $7.4B
- — CENTERPOINT ENERGY RESOURCES CORP: last 2017-12-31, peak $6.6B
- — Sinclair Broadcast Group, LLC: last 2022-12-31, peak $6.1B
- — SOUTHERN CO GAS: last 2015-12-31, peak $5.4B
- — DTE Electric Co: last 2014-12-31, peak $5.3B
- HMY HARMONY GOLD MINING CO LTD (ZAR): last 2023-06-30
- ONCY ONCOLYTICS BIOTECH INC (CAD): last 2021-12-31
- OBE OBSIDIAN ENERGY LTD. (CAD): last 2020-12-31
- BCH BANK OF CHILE (CLP): last 2022-12-31
- — HSBC BANK PLC (GBP): last 2022-12-31
- AEG AEGON LTD. (EUR): last 2022-12-31
- AZUL AZUL SA (BRL): last 2019-12-31
- ATHE ALTERITY THERAPEUTICS LTD (AUD): last 2018-06-30
- — BANCOLOMBIA SA (COP): last 2020-12-31
- CRDL Cardiol Therapeutics Inc. (CAD): last 2021-12-31

Known causes (mapping 1.4.1 notes): banks reporting in IFRS (21, such as HSBC, Santander, BBVA, UBS, SMFG) tag their total operating income only in company-specific extension tags, which companyfacts leaves out, and ifrs-full has no standard total; adding net interest and net fee income would leave out trading and other income, so their revenue stays absent rather than built. Williams' total and contract revenue disagree in the same 10-K (eliminations); the income-statement line would decide it, measured for a later mapping.

## LEI coverage

- USD reporters with $1B+ revenue (active): 1,542 of 1,898 (81.2%)
- Non-USD reporters (active, any size): 296 of 529 (56.0%)
- All active reporters: 3,881 of 7,501 (51.7%)
- The rest: SEC records give the home state, not the state of incorporation, for some filers, and GLEIF does not hold some entities under these names (Chevron).

## Successor registrants (K-05)

33 pairs found in ten years, all hand-checked against the successor's first periodic report: 16 stored (holding company reorganisations and accounting predecessors, each with the sentence quoted), 17 rejected (mergers whose accounting acquirer was another company, or no sentence).

## Unreconciled segments (E-4)

Segment figures are shown with status unreconciled when they do not add up to the consolidated figure within 1% and no reconciling item is tagged. Causes, per filing, kind, metric and year:

- segments above the total (overlapping breakdowns, subtotals): 11,620 (43%)
- no consolidated figure under the same tag: 7,667 (28%)
- segments far above the total (several breakdowns mixed): 3,053 (11%)
- a single segment tagged: 3,047 (11%)
- segments below the total (partial disclosure): 1,739 (6%)
- other (signs, zero or negative totals): 43 (0%)

### Two-axis segments and single-member blocks (E-4c, 2026-11-22)

Segments tagged on two axes (XOM: each segment by US and non-US) are now summed over the other axis when no member of that axis holds others and the segments then add up to the consolidated figure within 1%; one-axis figures win member by member. The revenue tag whose segments add up (and are finer than an all-segments total) is preferred, and the all-segments total is never shown beside real segments. A kind with one member that never adds up is hidden, with its reason in the API.

Dry run against every company's latest report before the reload: 417 of 4,174 blocks changed: 206 kinds added, 108 moved from unreconciled to ok, 140 changed values or members within an ok block; none removed and none from ok to unreconciled. Hand-check: a first sample of 30 found 2 wrong (an all-segments total counted twice, an intersegment line shown as a product); after tightening, a fresh seeded random sample of 30 found 1 (a company-named total, then fixed).

The 358 companies whose latest block had at most one member per kind: 21 now show segments that add up; 210 are single-segment companies (the one segment is the consolidated figure); 75 had a single unreconciled member, now hidden; 52 report segment profit only, no revenue by segment. XOM: Energy Products $291.6B, Upstream $107.2B, Chemical Products $33.0B, Specialty Products $20.5B; with corporate and eliminations, $332.2B, the consolidated figure exactly.

## First reported in earnings releases (E-2)

Figures an 8-K item 2.02 release stated with the same value, of those it could have stated (the period's own 10-Q or 10-K, a stored release in its window): 76,370 of 103,827 (73.6%). Balance-sheet and cash-flow figures are often not printed in releases.

| Metric | Matched | Eligible | Rate |
|---|---|---|---|
| cash_and_equivalents | 7,207 | 10,873 | 66% |
| eps_basic | 9,138 | 11,756 | 78% |
| eps_diluted | 10,437 | 11,759 | 89% |
| gross_profit | 4,469 | 5,613 | 80% |
| net_income | 7,362 | 11,675 | 63% |
| operating_cash_flow | 3,214 | 5,999 | 54% |
| operating_income | 6,292 | 10,211 | 62% |
| revenue | 10,865 | 12,329 | 88% |
| stockholders_equity | 7,493 | 11,293 | 66% |
| total_assets | 9,893 | 12,319 | 80% |

## Spot check against the 10-K as filed

| Company | FY end | Metric | Provenance | 10-K as filed | Check | Filing |
|---|---|---|---|---|---|---|
| AAPL | 2026-09-26 | revenue | 478,834M | …Total net sales (1) / 114,477 / 102,466 / 478,834 / 416,161… | same (earnings release) | [10-K](https://www.sec.gov/Archives/edgar/data/320193/000032019326000026/0000320193-26-000026-index.html) |
| AAPL | 2026-09-26 | net_income | 132,175M | …Net income / $30,711 / $27,466 / $132,175 / $112,01… | same (earnings release) | [10-K](https://www.sec.gov/Archives/edgar/data/320193/000032019326000026/0000320193-26-000026-index.html) |
| AAPL | 2026-09-26 | total_assets | 404,548M | …Total assets / $404,548 / $359,24… | same (earnings release) | [10-K](https://www.sec.gov/Archives/edgar/data/320193/000032019326000026/0000320193-26-000026-index.html) |
| AAPL | 2026-09-26 | eps_diluted | 8.98 | …Diluted / $2.10 / $1.85 / $8.98 / $7.46… | same (earnings release) | [10-K](https://www.sec.gov/Archives/edgar/data/320193/000032019326000026/0000320193-26-000026-index.html) |
| JPM | 2025-12-31 | revenue | 182,447M | 182,447M | same | [10-K](https://www.sec.gov/Archives/edgar/data/19617/000162828026008131/0001628280-26-008131-index.html) |
| JPM | 2025-12-31 | net_income | 57,048M | 57,048M | same | [10-K](https://www.sec.gov/Archives/edgar/data/19617/000162828026008131/0001628280-26-008131-index.html) |
| JPM | 2025-12-31 | total_assets | 4,424,900M | 4,424,900M | same | [10-K](https://www.sec.gov/Archives/edgar/data/19617/000162828026008131/0001628280-26-008131-index.html) |
| JPM | 2025-12-31 | eps_diluted | 20.02 | 20.02 | same | [10-K](https://www.sec.gov/Archives/edgar/data/19617/000162828026008131/0001628280-26-008131-index.html) |
| XOM (old CIK) | 2025-12-31 | revenue | 332,238M | 332,238M | same | [10-K](https://www.sec.gov/Archives/edgar/data/34088/000003408826000045/0000034088-26-000045-index.html) |
| XOM (old CIK) | 2025-12-31 | net_income | 28,844M | 28,844M | same | [10-K](https://www.sec.gov/Archives/edgar/data/34088/000003408826000045/0000034088-26-000045-index.html) |
| XOM (old CIK) | 2025-12-31 | total_assets | 448,980M | 448,980M | same | [10-K](https://www.sec.gov/Archives/edgar/data/34088/000003408826000045/0000034088-26-000045-index.html) |
| XOM (old CIK) | 2025-12-31 | eps_diluted | 6.70 | 6.70 | same | [10-K](https://www.sec.gov/Archives/edgar/data/34088/000003408826000045/0000034088-26-000045-index.html) |
| XOM (new CIK) | — | — | no annual report in the data | | | |
| DUK | 2025-12-31 | revenue | 31,741M | 31,741M | same | [10-K](https://www.sec.gov/Archives/edgar/data/1326160/000132616026000014/0001326160-26-000014-index.html) |
| DUK | 2025-12-31 | net_income | 4,968M | 4,968M | same | [10-K](https://www.sec.gov/Archives/edgar/data/1326160/000132616026000014/0001326160-26-000014-index.html) |
| DUK | 2025-12-31 | total_assets | 195,736M | 195,736M | same | [10-K](https://www.sec.gov/Archives/edgar/data/1326160/000132616026000014/0001326160-26-000014-index.html) |
| DUK | 2025-12-31 | eps_diluted | 6.31 | 6.31 | same | [10-K](https://www.sec.gov/Archives/edgar/data/1326160/000132616026000014/0001326160-26-000014-index.html) |
| O | 2025-12-31 | revenue | 5,749M | 5,749M | same | [10-K](https://www.sec.gov/Archives/edgar/data/726728/000072672826000011/0000726728-26-000011-index.html) |
| O | 2025-12-31 | net_income | 1,059M | 1,059M | same | [10-K](https://www.sec.gov/Archives/edgar/data/726728/000072672826000011/0000726728-26-000011-index.html) |
| O | 2025-12-31 | total_assets | 72,796M | 72,796M | same | [10-K](https://www.sec.gov/Archives/edgar/data/726728/000072672826000011/0000726728-26-000011-index.html) |
| O | 2025-12-31 | eps_diluted | 1.17 | 1.17 | same | [10-K](https://www.sec.gov/Archives/edgar/data/726728/000072672826000011/0000726728-26-000011-index.html) |
| BRK | 2025-12-31 | revenue | 371,444M | 371,444M | same | [10-K](https://www.sec.gov/Archives/edgar/data/1067983/000119312526083899/0001193125-26-083899-index.html) |
| BRK | 2025-12-31 | net_income | 66,968M | 66,968M | same | [10-K](https://www.sec.gov/Archives/edgar/data/1067983/000119312526083899/0001193125-26-083899-index.html) |
| BRK | 2025-12-31 | total_assets | 1,222,176M | 1,222,176M | same | [10-K](https://www.sec.gov/Archives/edgar/data/1067983/000119312526083899/0001193125-26-083899-index.html) |
| BRK | | eps_diluted | not reported (Berkshire reports basic EPS per Class A share) | | | |
| LIN | 2025-12-31 | revenue | 33,986M | 33,986M | same | [10-K](https://www.sec.gov/Archives/edgar/data/1707925/000162828026011430/0001628280-26-011430-index.html) |
| LIN | 2025-12-31 | net_income | 6,898M | 6,898M | same | [10-K](https://www.sec.gov/Archives/edgar/data/1707925/000162828026011430/0001628280-26-011430-index.html) |
| LIN | 2025-12-31 | total_assets | 86,817M | 86,817M | same | [10-K](https://www.sec.gov/Archives/edgar/data/1707925/000162828026011430/0001628280-26-011430-index.html) |
| LIN | 2025-12-31 | eps_diluted | 14.61 | 14.61 | same | [10-K](https://www.sec.gov/Archives/edgar/data/1707925/000162828026011430/0001628280-26-011430-index.html) |

27 of 27 figures match the filing as filed.

