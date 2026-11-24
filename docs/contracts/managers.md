# Q-02 Fund managers (Form 13F): portfolios, quarter-on-quarter changes, most bought and sold

Three endpoints on the Form 13F holdings already stored (the SEC's Form 13F data sets, plus
EDGAR for some managers). Shares only: positions in principal amount and options are not in
13F holdings here. Information about what managers reported, not signals.

## Values

`value_basis` is `"usd"` in every response: all values are whole US dollars. Form 13F
information tables filed before 3 January 2023 reported thousands; those are multiplied by
1,000 when stored, keyed on the filing date as the SEC's instructions are. The first quarter
filed in dollars is 2022-12-31 (filed in 2023). A manager's history never mixes the two bases.

Coverage today: every manager's filings for the quarters 2025-09-30 to 2026-09-30 (about 11,000
managers a quarter); earlier quarters only for some managers. `coverage` in each response gives
the first and last complete quarter loaded, and `history` lists only quarters loaded for that
manager, so the page never implies a longer record.

**Reporting lag.** Managers file Form 13F up to 45 days after each quarter end, so holdings are
as of the quarter end, not today. Every response carries `reporting_lag` (that sentence, for the
page to show). A quarter is shown once its 45-day filing deadline has passed and the loaded data
reaches it.
Amendments per manager and quarter, in filing order: an original 13F-HR or a 13F-HR/A
RESTATEMENT replaces what was there; a 13F-HR/A NEW HOLDINGS adds positions. With `as_of`, only
filings made by that date count.

## 1. `GET /v1/managers?q=&limit=`

Managers by name (as filed on their latest 13F cover page, words in any order) or CIK.

```json
{
  "data": [
    {"cik": "0001067983", "name": "Berkshire Hathaway Inc", "company_cik": "0001067983",
     "latest_quarter": "2026-09-30", "positions": 41, "value_usd": 287104512033.0}
  ],
  "meta": {"limit": 20, "has_more": false},
  "reporting_lag": "Form 13F holdings are as of the quarter end and are filed up to 45 days after it."
}
```

`company_cik` is set when the manager is also a company covered here, else `null`. `q` is 2-100
characters; `limit` 1-50, default 20.

## 2. `GET /v1/managers/{cik}?quarter=&as_of=&sort=&limit=&offset=`

One manager's portfolio for a quarter (default: the latest complete one), compared with the
quarter before.

| Parameter | Values | Default |
|---|---|---|
| `quarter` | a quarter end, e.g. `2026-09-30` | the latest complete quarter |
| `as_of` | ISO date: only filings made by then | none |
| `sort` | `value` (largest first), `change` (largest share change in value terms first), `name` | `value` |
| `limit` | 1-500 | 100 |
| `offset` | 0-10,000 | 0 |

```json
{
  "manager": {"cik": "0001067983", "name": "Berkshire Hathaway Inc", "company_cik": "0001067983"},
  "quarter": "2026-09-30",
  "previous_quarter": "2026-06-30",
  "value_basis": "usd",
  "reporting_lag": "Form 13F holdings are as of the quarter end and are filed up to 45 days after it.",
  "filing": {"accession_number": "0000950123-26-011111", "form": "13F-HR",
             "filed_date": "2026-11-14", "source_url": "https://www.sec.gov/Archives/...",
             "amendments": [{"accession_number": "...", "form": "13F-HR/A",
                             "amendment_type": "NEW HOLDINGS", "filed_date": "...",
                             "source_url": "https://www.sec.gov/Archives/..."}],
             "confidential_omitted": false},
  "totals": {"value_usd": 287104512033.0, "positions": 41,
             "matched_value_usd": 286900000000.0, "matched_positions": 39,
             "previous_value_usd": 279000000000.0, "previous_positions": 42},
  "positions": [
    {"issuer": {"cik": "0000320193", "name": "Apple Inc.", "ticker": "AAPL"},
     "class_label": "Common stock", "title_of_class": "COM",
     "shares": 280000000, "value_usd": 71234000000.0, "pct_of_portfolio": 24.81,
     "change": {"status": "reduced", "shares_previous": 300000000,
                "shares_change": -20000000, "shares_change_pct": -6.67}}
  ],
  "exited": [
    {"issuer": {"cik": "...", "name": "...", "ticker": "..."}, "class_label": "Common stock",
     "shares_previous": 1000000, "value_previous_usd": 52000000.0}
  ],
  "history": [
    {"quarter": "2026-09-30", "value_usd": 287104512033.0, "positions": 41,
     "filing": {"accession_number": "...", "filed_date": "2026-11-14",
                "source_url": "https://www.sec.gov/Archives/..."}}
  ],
  "coverage": {"first_complete_quarter": "2025-09-30", "last_complete_quarter": "2026-09-30"},
  "meta": {"limit": 100, "offset": 0, "has_more": false, "next_offset": null},
  "labels": {"disclaimer": "Information, not signals. Not investment advice."},
  "notes": ["..."]
}
```

### Field rules

- **One position per company and share class.** A manager's rows for one security (investment
  discretion, other managers) are added up, as stored. `class_label` is the plain label used
  on company pages (`Common stock`, `Class A common stock`, `American depositary shares`, ...);
  `title_of_class` is as filed. Classes are never added together; ADS counts are never added to
  share counts.
- `issuer` is the company covered here that the position's security belongs to (the internal
  CUSIP map): `{cik, name, ticker}`. A position whose security is not matched to a company here
  is still listed, with `issuer: {"cik": null, "name": "<issuer name as filed>", "ticker":
  null}`: the name most managers gave that security on their 13Fs for the quarter (stored per
  security when the data set is loaded). **No CUSIP is ever returned.**
  `totals.matched_value_usd` and `matched_positions` count those matched to a company here.
- `pct_of_portfolio` is **derived**: the position's value over `totals.value_usd`.
- `change.status`: `new` (not held the quarter before), `added`, `reduced`, `unchanged`, compared
  on shares of the same company and class. `exited` lists positions held the quarter before and
  not now, **only when the manager filed holdings for this quarter** (no filing yet is not an
  exit). Changes compare shares, never values, so price moves are not read as buying or
  selling. When the quarter before is not loaded for the manager, `change` is `null` and
  `exited` is empty, with a note.
- `sort=change` orders by the absolute share change times this quarter's price per share (value
  over shares), so a large sale and a large purchase both rank high.
- `totals.value_usd` is the sum of the manager's positions as stored (shares only); a 13F's own
  cover-page total can differ (it includes options and principal-amount rows).
- `filing` is the 13F-HR the quarter's positions come from, with any amendments applied listed
  in `amendments`; `confidential_omitted` is `true` when the manager asked for confidential
  treatment of some positions (they are then missing here as on EDGAR).
- `history` is every loaded quarter for this manager, newest first, as stored (after
  amendments), with its filing.
- Links are sec.gov/Archives filing pages only. No API URLs, no fetch or detection times, no
  CUSIPs.

## 3. `GET /v1/managers/activity?quarter=&direction=&min_holders=&limit=`

"Most bought" and "most sold by funds" in a quarter, per company and class, from every
manager's change against the quarter before.

| Parameter | Values | Default |
|---|---|---|
| `quarter` | a quarter end | the latest complete quarter |
| `direction` | `bought` or `sold` | `bought` |
| `min_holders` | managers holding it in either quarter, 1-1,000 | 20 |
| `limit` | 1-100 | 50 |

```json
{
  "quarter": "2026-09-30", "previous_quarter": "2026-06-30", "direction": "bought",
  "value_basis": "usd",
  "reporting_lag": "Form 13F holdings are as of the quarter end and are filed up to 45 days after it.",
  "data": [
    {"issuer": {"cik": "...", "name": "...", "ticker": "..."}, "class_label": "Common stock",
     "managers_new": 120, "managers_added": 640, "managers_reduced": 410, "managers_exited": 35,
     "net_managers": 315, "holders": 1450, "holders_previous": 1365,
     "shares": 812000000, "shares_previous": 790000000, "shares_change_pct": 2.78}
  ],
  "labels": {"disclaimer": "Information, not signals. Not investment advice."},
  "notes": ["..."]
}
```

- Only managers that filed holdings for both quarters count for `added`, `reduced` and
  `exited`; `new` counts managers holding it now and not before.
- `net_managers` is (new + added) − (reduced + exited). `bought` ranks by it, highest first;
  `sold` lowest first; ties by `shares_change_pct`.
- `shares` and `shares_previous` are the sums over all managers holding it; they are 13F
  positions, not the company's shares outstanding.
- Only securities matched to a company here are ranked (a name as filed is not enough to add
  managers' positions together safely).

## Errors and access

- `404 manager_not_found` for a CIK with no 13F stored. `422 invalid_parameter` for a date that
  is not a quarter end, a quarter not loaded, or a bad sort or limit.
- The demo key: managers search and the activity list work, at most 10 rows, a larger `limit`
  trimmed with a note; a manager's portfolio at most 10 positions.
- Usual rate limits and plan limits apply.

## MCP and chat

- MCP tools `search_managers`, `manager_portfolio`, `fund_activity`.
- Chat answers "what did Berkshire buy last quarter", "most bought stocks by funds", "who sold
  Apple" with the rows, each linked to its 13F, and the disclaimer.

## Gate before release

- A dry run of 10 managers' portfolios and both activity lists, then a hand-check of 30 random
  positions against the 13F information table XML (shares and value per class after amendment
  precedence, the change against the quarter before), including a manager whose table has put
  and call rows (left out: shares only), an amended 13F-HR/A, an unmatched position's name as
  filed, and one pre-2023 filing if any are loaded. At most 1 wrong. The issuer-name table is a
  data load of its own: dry run, then 30 names hand-checked against the filings.
- R-2: p95 under 500 ms for search, a large portfolio (Berkshire, Vanguard) and the activity list.
