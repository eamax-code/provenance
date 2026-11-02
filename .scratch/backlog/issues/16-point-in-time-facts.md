# 16: Point-in-time facts ("what was known on date X")

**What to build:** An `as_of` date on the facts endpoints, so a backtest sees only what had been filed with the SEC by that date. The answer is the latest observation filed on or before `as_of`, not the value as later restated. The data already supports this: each fact row is one observation with its filing date and accession number.

**Blocked by:** none

**Status:** done

- [x] `GET /v1/companies/{cik}/facts?as_of=YYYY-MM-DD` ignores observations filed after `as_of`, and observations with no filing date; `revision_count` counts only revisions known by then
- [x] Derived quarters are computed only from observations filed by `as_of`
- [x] `GET /v1/facts/screen?as_of=` ranks companies on what was known at that date
- [x] The response echoes `as_of` and a note that `filed_date` is a date, so a filing accepted after the market closed on `as_of` is included (use the previous day for strict backtests)
- [x] Tests: a restated value returns the original before the restatement's filing date and the restatement after it
- [x] Found while testing: tag-conflict quality used later filings; mapping 1.1.0 judges conflicts per filing
