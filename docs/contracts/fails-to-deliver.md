# Q-06 Fails-to-deliver (SEC, per company)

Status: **built** (2026-11-25), for ui. The UI sketch is PM-approved: an Ownership-tab section,
a table and chart per settlement date, one sub-table per symbol and share class.

The SEC publishes, twice a month, the fails-to-deliver recorded at NSCC for every equity
security. These are information about settlement, not signals. Fails-to-deliver "are not
necessarily the result of short selling, and are not evidence of abusive short selling or
'naked' short selling" (the SEC's words). **Not investment advice.**

## Source and coverage

- The SEC's Fails-to-Deliver Data page (Data & Research, Data Library, sec-markets-data). The data
  are half-month pipe-delimited files, zipped, named `cnsfails{YYYYMM}{a|b}.zip`: `a` is the first
  half of the month, published at about the end of the month, and `b` the second half, at about
  the 15th of the next month. Before July 2009 the files are monthly. The SEC adds: "We cannot
  guarantee that the data will be posted by a particular date. We cannot guarantee the accuracy
  of the data."
- The record layout is `SETTLEMENT DATE` (8 digits), `CUSIP`, `SYMBOL`, `QUANTITY (FAILS)`,
  `DESCRIPTION` (company name, up to 30 characters) and `PRICE` (closing price on the previous
  day).
- We load from July 2009, the half-month files, for the companies stored here. The page lists
  416 files from February 2004 to October 2026.
- **Matching.** A row belongs to a company through its CUSIP in `issuer_cusips`, internally only.
  **The CUSIP is never returned.** A row whose CUSIP is not mapped is not shown, and a response
  `notes` line counts such rows when any of the issuer's other classes are mapped. A ticker alone
  never matches: tickers are reused.

## `GET /v1/companies/{cik}/fails-to-deliver?since=&until=&as_of=`

| Parameter | Values | Default |
|---|---|---|
| `since`, `until` | ISO dates on the settlement date, inclusive; at most 366 days apart | the 180 days to the latest settlement date |
| `as_of` | ISO date: only files published by then (no look-ahead) | none (today) |

```json
{
  "cik": "0000012345",
  "data": [
    {
      "symbol": "ABCD",
      "class_label": "Class A common stock",
      "description": "ABCD CORP CL A",
      "rows": [
        {"settlement_date": "2026-10-14", "quantity": 182345, "price": 12.41,
         "value": {"value": 2262901.45, "derived": true, "basis": "quantity x price"},
         "source": {"file": "cnsfails202610a.zip", "published": "2026-10-31"}}
      ]
    }
  ],
  "coverage": {"from": "2009-07-01", "through": "2026-10-31", "latest_file": "cnsfails202610b.zip"},
  "notes": ["Information, not signals. Not investment advice.",
            "Fails-to-deliver are not necessarily the result of short selling..."]
}
```

### Labels (PM, 2026-11-25; the UI uses these words)

- **Quantity:** "The balance of shares that had failed to settle and were still outstanding on
  that settlement date, across all clearing members (NSCC), as the SEC publishes it. It is a
  running balance, not the day's new fails, and it does not show how old the fails are."
- **Missing dates:** "A date with no row had no fails balance, or its file is not yet published."
  (No 10,000-share threshold from 2008 on.)
- **Price:** the previous day's close as filed; "." in the file (not available or under a penny)
  is `null` and shown as "—".
- **Value:** derived, the balance times the price.
- **Coverage:** from July 2009 (the half-month files); `coverage` gives the range loaded.

### Field notes

- **Which dates appear (confirmed from the SEC's data description).** From 16 September 2008 the
  files "include all securities with a balance of total fails-to-deliver as of a particular
  settlement date". A security and date with a zero balance has no record ("If the aggregate net
  balance of shares that failed to be delivered is zero ... then no record will be present"). Before
  16 September 2008 only balances of at least 10,000 shares appear. We load from July 2009, so a
  missing date means a zero balance, or a file not yet published; it never means under 10,000.
- **`quantity` (confirmed).** "The values of total fails-to-deliver shares represent the aggregate
  net balance of shares that failed to be delivered as of a particular settlement date", that is,
  "the balance level outstanding recorded in the National Securities Clearing Corporation's
  ('NSCC') Continuous Net Settlement (CNS) system aggregated over all NSCC members." It is
  cumulative: all fails outstanding until that day, plus new fails that day, less those settled.
  It is "not a daily amount of fails", and "the age of fails cannot be determined" from it. The UI
  says "fails outstanding", never "new fails".
- **`price`** is as filed: "the closing price of the security on the previous day as long as the
  price is available and is greater than one penny"; `null` where the file has "." (unavailable or
  under a penny). The SEC does not guarantee it matches other sources' closing prices.
- **`value`** is derived (quantity times price) and `null` when `price` is. It is never summed
  across rows or classes.
- **One sub-table per symbol and class**, never summed across classes. `class_label` is the class
  as titled where the CUSIP is mapped (`issuer_cusips.class_title`), else `null`. `description` is
  the file's company name, as filed.
- **`source.file`** names the SEC file as text, with no link: it is not an EDGAR Archives document.
  `source.published` is the file's publication date: its Last-Modified date at the SEC (the date we
  first read it when the SEC gives none). `as_of` filters on it, so a settlement date is known only
  from its file's publication.

## Errors and access

As the other company endpoints: 404 `company_not_found`; 422 on dates; readers' keys; the demo key
covers the showcase companies. An empty `data` with a `notes` line when no CUSIP is mapped.

## Load (pv)

- `scripts/load_fails_to_deliver.py`: the file list from the SEC page and each ZIP, through
  `SecClient` (8 requests per second or fewer, cached, stopping on 403 or 429); a dry run first
  (rows, companies matched, unmatched CUSIPs), then the write. The hourly job takes new files as
  they appear.
- **Gate:** 30 stored rows matched against the file's own lines (settlement date, quantity and
  price, the symbol and the CUSIP's company), 30 of 30, plus one unmatched CUSIP shown absent.
