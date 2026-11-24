# Q-03 Insider screener (open-market buys and sales across companies)

`GET /v1/insider-transactions?type=&since=&until=&as_of=&min_value=&max_value=&role=&title=&cik=&owner_cik=&plan_10b5_1=&cluster=&sort=&limit=&offset=`

Open-market purchases (Form 4 code `P`) and sales (code `S`) across every company, one row per
Form 4: its lines of one code are added up, with the weighted average price. Built from the Form
3/4/5 data already stored (the SEC's quarterly insider data sets, plus Form 4s read as filed for
the newest weeks). Information about what insiders reported, not signals.

| Parameter | Values | Default |
|---|---|---|
| `type` | `buy` (code P), `sell` (code S) or `all` | `all` |
| `since`, `until` | ISO dates on the transaction date, inclusive; at most 366 days apart | the 30 days to `until` |
| `as_of` | ISO date: only Form 4s filed by then (no look-ahead); `until` defaults to it | none (today) |
| `min_value`, `max_value` | US dollars, on the row's `value` | none |
| `role` | comma-separated: `director`, `officer`, `ten_percent_owner`, `other` | none |
| `title` | words in the officer title as filed, e.g. `ceo`, `chief financial` (case ignored) | none |
| `cik` | one issuer CIK | none |
| `owner_cik` | one reporting person's CIK | none |
| `plan_10b5_1` | `true` (the Form 4 ticks the Rule 10b5-1 box) or `false` (it does not) | none |
| `cluster` | `true`: only purchases counted in an F-03 cluster-buying event | none |
| `sort` | `date` (newest transaction first), `value` (largest first) or `filed` (newest filing first) | `date` |
| `limit` | 1-100 | 50 |
| `offset` | 0-5000 | 0 |

`role` and `title` keep a row when any of its reporting owners matches.

## Response

```json
{
  "data": [
    {
      "issuer": {"cik": "0000320193", "name": "Apple Inc.", "ticker": "AAPL"},
      "owners": [
        {"cik": "0001214156", "name": "Timothy D Cook", "role": "CEO",
         "is_director": true, "is_officer": true, "is_ten_percent_owner": false,
         "officer_title": "Chief Executive Officer"}
      ],
      "type": "sell",
      "trans_code": "S",
      "first_date": "2026-10-02",
      "last_date": "2026-10-03",
      "lines": 4,
      "shares": 129963,
      "average_price": 254.83,
      "value": 33118461.0,
      "shares_after": 3280295,
      "holdings_change_pct": -3.8,
      "direct_indirect": "D",
      "plan_10b5_1": true,
      "cluster": null,
      "filing": {"accession_number": "0001214156-26-000012", "form": "4",
                 "filed_date": "2026-10-03",
                 "source_url": "https://www.sec.gov/Archives/edgar/data/320193/000121415626000012/"}
    }
  ],
  "meta": {"limit": 50, "offset": 0, "has_more": true, "next_offset": 50},
  "filters": {"type": "all", "since": "2026-09-04", "until": "2026-10-03", "as_of": null},
  "through": "2026-11-23",
  "labels": {"disclaimer": "Information, not signals. Not investment advice."},
  "notes": ["...", "..."]
}
```

(Values above are illustrative.)

## Field rules

- **One row per Form 4 and code.** A Form 4 with both purchases and sales gives two rows. Lines of
  one code are added up: `shares` is their sum, `average_price` is weighted by shares, and
  `value` is shares × price summed over lines with a price. `first_date` and `last_date` are the
  earliest and latest transaction dates on those lines; `lines` counts them.
- **Derivative rows (table II), grants, exercises, gifts and tax withholding are not included.**
  The per-company `/v1/companies/{cik}/insider-transactions` keeps every code.
- `value` is `null` when no line has a price. A line priced 0 counts as no price.
- `shares_after` is the holding after the last line, as filed. `holdings_change_pct` is
  **derived**: `shares` against the holding before the trades (`shares_after` plus the shares
  sold, or minus the shares bought). It is `null` when `shares_after` is missing or the holding
  before would be 0 or less.
- `direct_indirect` is `D` or `I` as filed on the last line; when the lines mix both, it is
  `mixed`.
- `plan_10b5_1` is the Form 4's own checkbox: `true`, `false`, or `null` for Form 4s filed before
  the checkbox existed (April 2023).
- `owners` lists every reporting owner of a joint Form 4 (a fund and its general partner, say).
  The shares are the filing's, counted once, not once per owner. `role` is the same label the
  company pages use.
- `cluster` is `null`, or, for a purchase counted in an F-03 cluster-buying event, that event:
  `{"event_date", "insiders", "first_trade", "event_filing": {accession_number, source_url}}`.
  The rule: same issuer, this owner among the event's insiders, and the trade dated from the
  event's first trade to the event's date. Events are three or more insiders buying in the open
  market within 30 days.
- `issuer.name` is the company's display name; `ticker` is its primary ticker or `null`.
- `filing.source_url` is the Form 4's sec.gov/Archives folder. No other link is given. No API
  URLs, no fetch or detection times, no CUSIPs.
- Transactions dated after their own filing date, or more than three years before it, are left
  out as filed errors (3,274 of 571,177 P and S lines today, such as the year 0023 for 2023). The
  per-company endpoint still shows them.
- `through` is the date the stored Form 4 data runs to.
- `notes` say how rows are built (one per Form 4 and code; open market only) and when the window
  reaches past `through`.

## Errors and access

- `422 invalid_parameter`: a bad date, a range over 366 days or with `since` after `until`, a
  bad CIK, an unknown role, a `title` over 40 characters, `min_value` above `max_value`, or
  `cluster=true` with `type=sell`.
- The demo key covers the public showcase companies only: rows from others are left out, and
  `cik` outside them is `403 demo_scope`. The demo key gets at most 10 rows; a larger `limit` is
  trimmed, not refused, with `has_more` false and a note.
- Usual rate limits and plan limits apply. CSV is the page's own export within plan limits; the
  API returns JSON.

## MCP and chat

- MCP tool `screen_insider_trades`, with the same parameters.
- Chat answers "which insiders bought over $1M last month", "CEO sales this week", "cluster buying
  in the last 30 days" with the top rows, each linked to its Form 4, and the disclaimer.

## Gate before release

- A dry run of the default screen and 5 filtered screens, then a hand-check of 30 random rows
  against their Form 4 XML (shares, weighted price, value, dates, owner, role, 10b5-1 box, and
  the cluster flag against the F-03 event). At most 1 wrong.
- R-2: p95 under 500 ms for the default screen and the filtered shapes.
