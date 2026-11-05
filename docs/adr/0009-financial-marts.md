# ADR 0009: Precomputed financial marts; point in time still reads observations

**Status:** accepted (2026-11-05)

`financial_facts` keeps every observation of every figure (5.6 million rows): restatements, the
same value repeated in later filings, and proxy statements that repeat net income. Each feature
chose "the value for a period" its own way, and the cross-company screen read thousands of rows
to rank companies.

**Decision.**
- `mart_financials` holds one value per company, metric, period class (annual or quarterly),
  unit and period end. Within a period it takes the annual report's observation when there is
  one (10-K, 20-F, 40-F, 10-KT), then the latest filed. It is the same rule the chat's brief and
  the public pages use. Each row keeps its form, filing date, accession number, XBRL tag,
  filing link, quality status and mapping version.
- Fiscal labels (`fiscal_year`, `fiscal_quarter`) come from `app/services/periods.py`, the only
  place that names periods. They are named by the period end and the company's year end, so
  52/53-week years and quarters that straddle a calendar year are labelled correctly.
- `mart_company_period` pivots the five annual USD figures into one row per company and fiscal
  year, with each figure's filing link, for exports and quick reads.
- Derived quarters (Q4 = annual − nine months) stay out of the marts and are still computed
  when asked for, as ADR 0003 decided. The marts hold only reported values.
- Point-in-time questions (`as_of`) keep reading `financial_facts`. A mart row is the answer as
  of today, and a cut-off date can change which observation was known.
- The screen reads the mart when no `as_of` is given (about 30–40 ms instead of 370 ms). A
  database without built marts falls back to the observations. It ranks and pages on the
  screen index alone (`value` is included in it) and reads whole rows only for the page shown,
  so a cold query no longer touches a table page per company: p95 46 ms with empty caches,
  against up to 750 ms before.

**Consequences.**
- `scripts/build_marts.py` rebuilds everything in about 2.5 minutes on the local data (1.9
  million mart rows). Ingesting a company refreshes its rows in about 0.1 s.
- Every new reader of "the figure for a period" should read the mart, not reimplement the
  choice.
