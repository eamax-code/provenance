# API contracts for the Explorer (X-01a, X-02, X-05, X-07)

Status: **contract**; built: X-05 (7919122), X-02 (5d6db75), X-01a (1406041), X-07 (published 2026-11-23 for provenance-ui). Built after the mapping
1.5.0 pass in this order: X-05, X-02, X-01a, X-07. Each lands with tests, an OpenAPI entry and an
R-2 line. Changes to a published contract are additive only (`docs/api-versioning.md`).

Common to all four:
- `X-API-Key` required (the Explorer is keyed). Plan limits and metering as for `/facts`: one
  request is one unit. The demo key works on the showcase companies only (`403 demo_restricted`
  elsewhere) and gets at most 10 rows on any list, as today.
- The standard error envelope: `404 company_not_found`, `422 invalid_parameter`, `429` with
  `Retry-After`.
- `as_of` (ISO date) everywhere it makes sense: only data filed by that date, no look-ahead. The
  response echoes `as_of` (`null` when absent).
- Every value links its filing (`source_url` / `filing_url` is a sec.gov/Archives document or
  index). Never a source API URL, `first_detected_at`, `source_updated_at` or a CUSIP.
- Money is in the company's reporting currency, unit stated per value; nothing is converted and
  mixed currencies are never summed (D-04). Derived values say `derived: true` and list inputs.

---

## X-01a Keyed company overview

`GET /v1/companies/{cik}/overview?as_of=`

The same payload, shape and `as_of` semantics as `GET /v1/public/companies/{cik}/overview`, for
**any** company (the public one is showcase-only). Blocks: `company` (identity, display name, LEI
and how it was matched, incorporation and its source, auditor), `key_figures`, `years`, `events`,
`ownership`, `segments`, `insider_activity`, `leadership`, plus the notes the public payload has.
Keyed responses are not cached publicly (`Cache-Control: private`). Built from stored data only:
no SEC fetch on read (a company not yet ingested is `404 company_not_found`, as `/facts`).

Provenance card fields (additive, on the public overview too): every value in `key_figures`,
`years[].sources` and the statement cells carries `source_tag` and `mapping_version` beside the
`accession_number`, `quality_status` and filing link it has today, so the card needs no second
call (keyless showcase visitors cannot make a keyed `/facts` call).

TTM (trailing twelve months), additive, in `key_figures` (and X-02 as an extra `TTM` column when
`period=annual`): for flow metrics (income statement and cash flow) the sum of the last four
quarters, each a quarter value as `/facts?period=quarterly` gives it (derived Q4s included and
marked); for balance-sheet metrics and `shares_outstanding`, the latest quarter-end value. Given
only when all four quarters exist, are consecutive, end within the last 15 months (or before
`as_of`) and share one unit; never mixed with the annual figure. Marked `derived: true`,
`formula: "sum of the last 4 quarters"` or `"latest balance"`, `inputs` listing each quarter's
period and accession. EPS TTM is not the sum of quarterly EPS: it is given only when the
company's own diluted weighted shares let it be derived, else null.

| Status | When |
|---|---|
| 200 | the overview |
| 404 `company_not_found` | unknown CIK |
| 403 `demo_scope` | the demo key outside the showcase (as every keyed endpoint) |

---

## X-02 Bulk financial statements

`GET /v1/companies/{cik}/statements/{statement}`

| Parameter | Values | Default |
|---|---|---|
| `statement` (path) | `income`, `balance`, `cash_flow` | |
| `period` | `annual`, `quarterly` | `annual` |
| `periods` | 1-20 columns (annual), 1-80 (quarterly) | 12 annual, 40 quarterly |
| `as_of` | ISO date | none |
| `include_derived` | `true`/`false`: quarters derived by subtraction (Q4 = FY − 9M) and the derived rows below. Only currency flows are derived (revenue, income, cash flows); weighted average shares, EPS and ratios do not add up over quarters, so their quarters are only as reported (2026-11-25) | `true` |

One request returns the whole statement: every row, up to `periods` columns, newest last.

Rows (the 32 normalised metrics; `public_float` is a cover figure and stays out):

| Statement | Rows, in order |
|---|---|
| `income` | revenue, cost_of_revenue, gross_profit, r_and_d, sga, operating_income, interest_expense, net_interest_income, pretax_income, income_tax, net_income, eps_basic, eps_diluted, shares_basic_weighted, shares_diluted_weighted |
| `balance` | cash_and_equivalents, current_assets, total_assets, current_liabilities, long_term_debt_current, long_term_debt, total_liabilities, stockholders_equity, retained_earnings, shares_outstanding |
| `cash_flow` | operating_cash_flow, capex, d_and_a, sbc, dividends_paid, share_repurchases |

Derived rows (only with `include_derived=true`, only when every input is present in the same unit
and period; `derived: true`, `formula`, `inputs`):

| Statement | Derived rows |
|---|---|
| `income` | gross_margin (gross_profit / revenue), operating_margin (operating_income / revenue), net_margin (net_income / revenue) |
| `balance` | current_ratio (current_assets / current_liabilities), debt_to_equity (long_term_debt / stockholders_equity) |
| `cash_flow` | free_cash_flow (operating_cash_flow − capex) |

As built (2026-11-23): derived rows use the ratio definitions `/facts` already uses for derived
figures, so a margin is a percentage to one decimal with `unit: "%"` (31.5, not 0.315), a
multiple has two decimals, and free cash flow is in the reporting currency.

YoY and common-size are client-side toggles over these values; the API does not send them.

Response:

```json
{
  "cik": "0000320193",
  "statement": "income",
  "period": "annual",
  "as_of": null,
  "reporting_currency": "USD",
  "mapping_version": "1.5.0",
  "columns": [
    {"key": "FY2024", "period_label": "FY2024", "period_fiscal_year": 2024,
     "period_start": "2023-10-01", "period_end": "2024-09-28", "calendar_period": "CY2024"}
  ],
  "rows": [
    {
      "metric": "revenue", "label": "Revenue", "unit_kind": "currency", "derived": false,
      "cells": [
        {
          "column": "FY2024", "value": 391035000000, "unit": "USD",
          "period_start": "2023-10-01", "period_end": "2024-09-28",
          "form_type": "10-K", "filed_date": "2024-11-01",
          "accession_number": "0000320193-24-000123",
          "source_url": "https://www.sec.gov/Archives/edgar/data/320193/000032019324000123/0000320193-24-000123-index.htm",
          "source_tag": "RevenueFromContractWithCustomerExcludingAssessedTax",
          "source_taxonomy": "us-gaap", "mapping_version": "1.5.0",
          "quality_status": "ok", "derived": false, "derivation": null
        }
      ]
    },
    {
      "metric": "operating_margin", "label": "Operating margin", "unit_kind": "percent",
      "derived": true, "formula": "operating_income / revenue",
      "cells": [{"column": "FY2024", "value": 31.5, "unit": "%", "derived": true,
                 "inputs": [{"metric": "operating_income", "accession_number": "0000320193-24-000123"},
                            {"metric": "revenue", "accession_number": "0000320193-24-000123"}]}]
    }
  ],
  "notes": ["Values are as reported in each filing, in the company's reporting currency."]
}
```

(Values in the example are illustrative.)

Rules:
- A cell is the value `/v1/companies/{cik}/facts` returns by default for that metric and period
  (the most recently filed eligible observation; restatements keep their originals there). Same
  selection, same `quality_status`; a missing value is `null`, never 0.
- A cell in a currency other than `reporting_currency` keeps its own `unit` and is never converted.
- `columns` is the union of the rows' periods, capped at `periods`, oldest first.
- `404 no_statement_data` when the company has no value for any row.
- `split_break` (2026-11-23, additive): on share and EPS rows when two adjacent columns are on
  different share bases, because a later filing restated some years for a split and earlier years
  stay as filed (Apple FY2017 5.2B shares, FY2018 19.8B): `{"between": ["FY2017", "FY2018"],
  "ratio_hint": "4:1", "text": "Shares and per-share figures before FY2018 are on the pre-split share basis, as reported in the filing each cites; …"}`
  (`"1:10"` for a reverse split); `text` is also in `notes`. Shown when shares jump by a
  near-whole factor (at least 1.9x) and EPS moves inversely. Values are never adjusted.
  S-02b (2026-11-24, additive): `split_date` (the split's effective date, from the reviewed split
  list `app/data/splits_reviewed.csv`, else `null`), `restated_in` (`{accession_number, form,
  filed_date, source_url}`: the filing behind the first column on the newer basis) and `earlier`
  (older splits, newest first, each with its own `split_date`; listed only when the reviewed list
  has them). The text then names the split: "10:1 split, June 2024: shares and per-share figures
  before FY2023 are on the pre-split share basis, as reported in the filing each cites; …", or, without a reviewed date, "(4:1, restated in the
  10-K filed 2020-10-30)". A pair whose income swing is over 2x counts only from the reviewed list.
  S-02c (2026-11-24): `reviewed` (bool); a reviewed row confirms a pair only when its effective date
  falls after the older column's filing and by the restating filing (`split_date` is that row's
  date: YYYY-MM-DD or YYYY-MM, as precise as the filing states it).
  A reviewed split also places its own break at the pair of columns whose filings bracket its
  date, even where the share-row guard cannot see it (no share row, or EPS turning from a loss
  to a profit). S-02d: a ratio may be fractional (`"3:2"`, adjusted by 1.5); two columns cited from
  one filing are never a break (a filing shows every year on one basis); and a reviewed split is
  placed only where exactly one column pair brackets its date.
  S-02e (2026-11-24): `split_break` is given only for reviewed splits. An unreviewed break is not
  shown at all, no note, no tag: a hand-check of 30 unreviewed "share basis changes here" notes
  found 7 with no basis change (share issuance, data mismatches, both years on one basis), against
  a bar of 3. `reviewed` is therefore always true when `split_break` is present. Only a reviewed split names its ratio in `text` and gets
  `split_adjusted`; any other break reads "The share basis changes here (restated in the 10-K filed
  <date>): shares and per-share figures before FYx are on the earlier share basis, as reported in
  the filing each cites, …" with no adjusted values and `ratio_hint: null` (a hand-check of 30 found IPO and
  merger share changes read as splits and reverse-split ratios off: about 80% wrong, so an
  unreviewed ratio is never shown, in the API, MCP or chat). As filed stays the
  default.
- `split_adjusted` (S-02, 2026-11-24, additive): beside the as-filed cells of a row with a
  `split_break`, the row on the post-split basis: `{"ratio": "4:1", "derived": true, "values":
  [...one per column...], "source": {"accession_number", "form", "filed_date", "source_url",
  "evidence": "eps_basic for the period ending 2018-09-29: 12.01 as filed 2018-11-05, 3 in the
  10-K filed 2020-10-30"}, "basis": "..."}`. Given only when a later filing restates a year by
  the break's own ratio; before the split each value is the later filing's restated one where
  it exists, else the as-filed value adjusted by that ratio. Only for reviewed splits (S-02c). Older reviewed splits are
  compounded into the values before them and listed under `earlier` (`[{ratio, before, source}]`). The as-filed cells stay the default.
- **Per column basis (2026-11-25).** For a reviewed split with a date (all but one row of the
  list), each share and EPS cell's basis comes from the date of the filing it cites: filed before
  the split's effective date, it is on the pre-split basis (a filing issued before a split does
  not reflect it; Piper Sandler's 10-K filed 2026-02-26: "As the stock split has not yet been
  effected, the accompanying financial statements and per-share data do not reflect the impact");
  filed after, on the post-split basis. This holds quarterly as well as annually: a 10-Q restates
  only the quarters it shows again, so Monster Beverage's Q1 and Q2 2026 (filed before its August
  2026 2:1 split) sit beside a restated Q3 2025 and a post-split Q3 2026. `split_break` adds
  `pre_split_columns` (every column on an earlier basis; they need not come first), `between` is
  the latest pair of adjacent columns on different bases, and when the pre-split columns are not
  simply the ones before it the text names them ("... figures in Q1 FY2026, Q2 FY2026 (filed
  before the split) are on the pre-split share basis ..."). `split_adjusted.values` adjusts every
  pre-split cell wherever it sits (a later filing's restated value where one agrees within 2%,
  else the as-filed value by the ratio, compounded across splits); a cell filed within a split
  given only to the month has `null`. `source` is the first filing found restating a shown period
  by the newest split's ratio, else the split list's own filing quote (`accession_number` and
  `source_url` then `null`). A statement whose cells are all on one basis has no break.

---

## X-05 Company timeline

`GET /v1/companies/{cik}/timeline`

| Parameter | Values | Default |
|---|---|---|
| `types` | comma list of `filing`, `8k_item`, `officer_change`, `auditor_change`, `ipo`, `insider`, `13f_quarter` | all |
| `from`, `to` | ISO dates (by item date) | the last 5 years |
| `as_of` | ISO date | none |
| `limit` | 1-200 | 50 |
| `cursor` | from `meta.next_cursor` | |

Items, newest first (date, then `id`, stable):

```json
{
  "cik": "0000320193",
  "as_of": null,
  "data": [
    {
      "id": "tl_8k_0000320193-26-000010_2.02",
      "date": "2026-10-30",
      "type": "8k_item",
      "event_type": "sec.results",
      "title": "Results of operations (8-K item 2.02)",
      "form_type": "8-K",
      "accession_number": "0000320193-26-000010",
      "filing_url": "https://www.sec.gov/Archives/edgar/data/320193/000032019326000010/0000320193-26-000010-index.htm",
      "upcoming": false,
      "details": {"item": "2.02"}
    }
  ],
  "meta": {"limit": 50, "has_more": true, "next_cursor": "..."},
  "notes": ["Information, not signals. Not investment advice."]
}
```

`details` by type (every item links its filing; `event_type` is the canonical name from
`GET /v1/event-types` where one exists):

| `type` | `date` | `details` |
|---|---|---|
| `filing` | filing date | `form_type`, `items` (8-K item codes), `report_date` |
| `8k_item` | filing date | `item`; one item per 8-K item code with an event type (restatement, auditor change, bankruptcy, results, …) |
| `officer_change` | filing date | `person`, `role`, `change` (`appointed`, `departed`), `effective_date` when stated; from 8-K item 5.02 |
| `auditor_change` | filing date | `from_firm`, `to_firm`, `source` (`8-K 4.01` or `annual report tags`), the linked 4.01 when both exist |
| `ipo` | the stage's date | `stage` (`priced`, `lockup_expiry`), terms from the final prospectus; `lockup_expiry` is `derived: true` and may be `upcoming: true` |
| `insider` | the last Form 4 date of the signal | `signal` (`cluster_buy`, `first_buy`, `large_sale`), `insiders`, `shares`, `value_usd`, the Forms 4 (`filings`: accession and URL each) |
| `13f_quarter` | the quarter's 45-day filing deadline | `quarter`, `holders_count`, `holders_change`, `flows` ({new, added, reduced, exited, not_filed}); `filing_url` is null: each holder's filing is listed by `/ownership` for that quarter |

Rules:
- With `as_of`: items whose filing was made by that date; 13F quarters complete by that date
  (same rule as `/ownership`); a derived lock-up date only if its prospectus was filed by then.
- `upcoming: true` only for derived future dates (a lock-up end after today or `as_of`).
- Unknown type in `types` → `422 invalid_parameter`. An empty timeline is `200` with `data: []`.
- Form 25 and 25-NSE (`event_type` `sec.delisting`): the title names the security the filing
  removes when the filing states it ("1.375% Notes due 2026 removed from listing", Apple's 25-NSE
  of 2026-11-09), else "Form 25: a security removed from listing". Never "Security delisted"
  alone: an exchange files 25-NSE for one class (often notes) while the common stock stays
  listed. The security comes from the filing's own description, read when the filing is
  ingested (not on read). On 2026-11-23, 377 active listed companies had a Form 25 or 25-NSE in
  the last year (448 filings; 164 companies in the last 90 days), all labelled "Security
  delisted" today; the same wording rule applies to the event feed's short label.

---

## X-07 Watchlists (stored per key)

Named lists of companies with chosen columns, stored on the server per API key (no account
work). Another key's list is `404` (never `403`, so ids are not probed). A list stores the key
id, its name, the CIKs, the columns and two timestamps; revoking the key deletes its lists in
the same transaction.

| Method and path | Body / parameters | Returns |
|---|---|---|
| `POST /v1/watchlists` | `{"name": "Energy majors", "ciks": ["34088", "93410"], "columns": ["revenue", "operating_margin", "latest_filing", "last_event", "holders_change"]}` | `201` the list |
| `GET /v1/watchlists` | `limit`, `offset` | the key's lists (no rows) |
| `GET /v1/watchlists/{id}` | | the list |
| `PATCH /v1/watchlists/{id}` | any of `name`, `ciks` (replaces, order kept), `columns` | the list |
| `DELETE /v1/watchlists/{id}` | | `204`; watches made from it stay (they are the key's watches) |
| `GET /v1/watchlists/{id}/rows` | `as_of` | one row per company with the chosen columns |
| `GET /v1/watchlists/{id}/events` | the X-05 parameters | the X-05 items of every company in the list, each with `cik` and `display_name` |
| `POST /v1/watchlists/{id}/watch` | `{"destination_type": "webhook", "destination": "https://…"}` | `201` `{"watch_ids": [...]}`: one existing company watch (`/v1/watches`) per company, with the usual signing, SSRF checks and plan limits |

The list:

```json
{"id": "wl_…", "name": "Energy majors", "ciks": ["0000034088", "0000093410"],
 "columns": ["revenue", "operating_margin", "latest_filing", "last_event", "holders_change"],
 "created_at": "2026-11-23T05:00:00Z", "updated_at": "2026-11-23T05:00:00Z"}
```

Columns:

| Column | Cell |
|---|---|
| any of the 32 metric keys, or a derived row of X-02 | the latest annual value as an X-02 cell, plus `yoy` (derived, with both inputs) |
| `reporting_currency` | the code |
| `latest_filing` | `form_type`, `filing_date`, `filing_url` |
| `last_event` | the latest X-05 item (`8k_item`, `officer_change`, `auditor_change`, `ipo`, `insider`) |
| `holders_change` | `quarter`, `holders_count`, `holders_change` from `/ownership` |

Limits: `name` 1-80 characters; up to 50 companies and 8 columns per list; lists per key: free 3,
paid plans 25 (a plan feature: defined once in `app/core/plans.py`, with `site/plans.json`
regenerated by `scripts/sync_plans.py`; the pricing page does not list watchlists until the
copy is approved); the demo key cannot create lists (`403 demo_restricted`). Unknown CIKs or columns
→ `422` naming them. A row whose company has no value for a column has `null` there, never 0.

Storage (one migration, applied before the code that reads it): `watchlists` (id, api_key_id,
name, columns, created_at, updated_at) and `watchlist_companies` (watchlist_id, cik, position).
Revoking a key hides its lists.
