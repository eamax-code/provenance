# Q-05 N-PORT: size and storage plan (no load yet)

Status: **plan, measured** (2026-11-25). One quarter (2026 Q3) was downloaded into the cache and counted, with no database writes (PM go for the measurement only). Retention: the last four quarters; scope: equity holdings matched to our companies, plus fund metadata (PM). The load waits on the owner's hosting choice (database size).

## What it is

Form N-PORT (N-PORT-P and NPORT-P/A) is filed by registered funds and ETFs other than money market
funds and reports their portfolio holdings. The SEC publishes the filings as quarterly data sets
of tab-delimited UTF-8 files extracted from the XML, amendments included and "as filed" (SEC
readme: "Data in this submitted form may contain redundancies, inconsistencies, and discrepancies
relative to prior submissions"). Coverage runs from October 2019, with up to 30 files a quarter.
Source: the SEC's Form N-PORT Data Sets page and its readme (`/files/nport_readme.pdf`, read
through the SEC client).

**For the product:** "which funds hold this company's shares, how many and what share of each
fund", beside 13F (managers) and 13D/G (5% holders) on the Ownership tab. N-PORT adds mutual
funds and ETFs by series, monthly.

## Size (from the SEC's page)

- 28 quarterly ZIPs, 2019 Q4 to 2026 Q3: **11.1 GB compressed**. Each is 229 to 691 MB (2022 Q3 is
  the largest); the last four quarters total 1.7 GB.
- Uncompressed size and row counts are not published. Tab-delimited text usually compresses 5 to
  10 times, so a quarter is an estimated 2 to 4.5 GB unzipped. Most of it is
  `FUND_REPORTED_HOLDING` (one row per holding per report) and its child tables (identifiers, debt,
  derivatives).
- **Measured (2026 Q3, 441 MB ZIP):** 32 files, 1.55 GB unzipped. `FUND_REPORTED_HOLDING` is
  908 MB, `IDENTIFIERS` 257 MB, `DEBT_SECURITY` 131 MB and the rest under 105 MB each. There are
  14,066 filings (13,938 NPORT-P and 128 NPORT-P/A) and **5,627,083 holdings**, of which **1,898,370
  are equities** (asset category EC or EP). **1,410,236 equities, 74%, match a company here**
  (1,409,268 by CUSIP, 968 by issuer LEI only), at **5,042 companies** in 8,249 filings.

## What we would store

Only what the Ownership view needs, matched to companies here; not the whole data set.

| Table | From | Rows kept | Columns |
|---|---|---|---|
| `nport_funds` | REGISTRANT, FUND_REPORTED_INFO, SUBMISSION | one per filing (series and report period) | accession, series id and name, registrant CIK and name, report period end, filing date, net assets, form (P or P/A) |
| `nport_holdings` | FUND_REPORTED_HOLDING, IDENTIFIERS | equity holdings (asset category EC and EP) whose CUSIP, ISIN or issuer LEI maps to a company here | accession, holding id, company CIK, balance and its unit, value in USD, percentage of the fund's net assets, payoff profile (long or short), asset category, title of the issue |

- **Matching:** CUSIP through `issuer_cusips` and ISIN or issuer LEI through the existing
  identity links. Matching is internal; the CUSIP is never returned (the owner rule). An
  unmatched holding is not stored, as with Q-06.
- **Amendments:** an NPORT-P/A replaces its original for that series and period; both are kept,
  the amended one is shown, and `as_of` filters on the filing date.
- **Projected Postgres size:** our closest tables measure 189 bytes a row with indexes
  (`holdings_13f`, 12.7M rows, 2.3 GB) and 221 (`fails_to_deliver`, 6.0M rows, 1.3 GB). An N-PORT
  holding row has more columns (balance and unit, USD value, percentage, payoff, category, title),
  so allow 250 to 300 bytes. That is **about 350 to 420 MB a quarter**, and **1.4 to 1.7 GB for
  four quarters**; fund metadata adds about 10 MB a quarter. That is a quarter of the earlier rough
  estimate, because a quarter has 5.6M holdings, not 30 to 40M.
- **Raw files:** the ZIPs are kept in `SEC_BULK_DIR/nport` (1.7 GB for four quarters, 11.1 GB for
  all) so reloads and matching changes need no SEC requests.

## Load and gate (after go)

1. Measured (above).
2. A dry run over the last four quarters: rows read, matched, companies, and bytes estimated from
   the measured row width.
3. Gate: 30 stored holdings matched against their N-PORT XML filing on EDGAR Archives (series,
   period, issuer, balance, value, percentage), at most 1 off. Plus one unmatched holding shown
   absent, not zero.
4. Then the write, and an endpoint contract (`/v1/companies/{cik}/fund-holders`) for ui. That is
   a separate contract step.

## Open questions for the PM

- Decided (PM): the last four quarters; equities matched to our companies plus fund metadata.
- **Open (owner):** the hosting plan's database size limit, which the measured 1.4 to 1.7 GB is
  put against before any load.
