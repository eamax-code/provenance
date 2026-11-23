# X-15 Calendar (company and watchlist)

`GET /v1/companies/{cik}/calendar?from=&to=&kinds=`
`GET /v1/watchlists/{id}/calendar?from=&to=&kinds=` (the key's own watchlist; the same items
for every company on it, each with its `company`)

| Parameter | Values | Default |
|---|---|---|
| `from`, `to` | ISO dates, at most 400 days apart | 90 days back to 180 days ahead |
| `kinds` | comma list of the kinds below | all |

```json
{
  "cik": "0000320193",
  "from": "2026-08-26", "to": "2027-05-23",
  "data": [
    {"date": "2026-12-26", "kind": "filing_deadline", "title": "10-Q due (period ending 2026-12-27)",
     "derived": true,
     "basis": "Large accelerated filer: 40 days after the quarter end (Form 10-Q, General Instruction A.1)",
     "company": {"cik": "0000320193", "name": "Apple Inc."},
     "source": {"accession_number": "0000320193-25-000079", "form": "10-K", "filed_date": "2025-10-31",
                "source_url": "https://www.sec.gov/Archives/...",
                "why": "filer status and fiscal year end as tagged on this report's cover"}},
    {"date": "2026-11-20", "kind": "late_notice", "title": "NT 10-Q filed",
     "derived": false, "company": {"cik": "...", "name": "..."},
     "source": {"accession_number": "...", "form": "NT 10-Q", "filed_date": "2026-11-20",
                "source_url": "https://www.sec.gov/Archives/..."}}
  ],
  "notes": ["Derived dates are computed from rules and the company's own filings; the company's actual filing date can differ."]
}
```

Kinds:

| kind | derived | What it is |
|---|---|---|
| `filing_deadline` | yes | 10-K and 10-Q due dates, from the fiscal year end and the filer category tagged on the latest annual report (`dei:EntityFilerCategory`). 10-K: 60, 75 or 90 days after the year end (large accelerated, accelerated, other). 10-Q: 40, 40 or 45 days after the quarter end. A date that falls on a weekend or US federal holiday moves to the next business day. 20-F and 40-F filers: the 20-F is due 4 months after the year end. |
| `late_notice` | no | An NT 10-K or NT 10-Q (Rule 12b-25) was filed. Its dated item is the filing date. |
| `lockup_expiry` | yes | IPO lock-up end, from the prospectus lock-up period (as `/v1/ipos` gives it) |
| `quiet_period_end` | yes | 25 days after the IPO (FINRA Rule 2241 research quiet period) |
| `annual_meeting` | no | The meeting date stated in the definitive proxy (DEF 14A) cover, when we read it. *Provisional*: it may ship empty in this window. |
| `proposed_sale_window_end` | yes | 90 days after a Form 144 notice, when no matching Form 4 sale was found by then (D-12) |

Rules:
- Items are sorted by date. A past deadline that the matching report already met shows
  `"met_by": {"accession_number", "filed_date", "source_url"}`. A past deadline that was not met
  shows `"met_by": null`; the ui says "not filed by the due date" only when a `late_notice`
  exists, otherwise "no report found".
- Every derived item has `basis`, the rule in one sentence. The ui marks it "derived".
- Watchlist calendars are capped at 500 items. When the cap is hit, `meta.truncated` is true.

| Status | When |
|---|---|
| 200 | items (may be empty) |
| 404 `company_not_found` / `watchlist_not_found` | unknown, or a watchlist another key owns |
| 422 `invalid_parameter` | a range over 400 days, or `from` after `to` |

MCP: the `company_calendar` tool, `{cik, from?, to?}`.
