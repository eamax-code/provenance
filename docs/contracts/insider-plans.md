# D-11 and D-12 Trading plans and proposed sales

`GET /v1/companies/{cik}/insider-plans?as_of=&since=&limit=`

There are two lists. `plans` holds the trading-plan disclosures from 10-Qs and 10-Ks (Item 408(a)
of Regulation S-K). `proposed_sales` holds the Form 144 notices, each joined to the Form 4 that
reported the sale.

| Parameter | Values | Default |
|---|---|---|
| `as_of` | ISO date: only filings filed by then | none |
| `since` | ISO date: only items dated on or after it (plan date or notice date) | two years before today, or before `as_of` |
| `limit` | 1-200, per list | 50 |

```json
{
  "cik": "0000320193",
  "as_of": null,
  "plans": [
    {
      "person_name": "Kevan Parekh",
      "title": "Senior Vice President and Chief Financial Officer",
      "action": "adopted",
      "plan_type": "rule_10b5_1",
      "date": "2025-11-21",
      "duration_days": 406,
      "expiration_date": "2026-12-31",
      "shares": null,
      "filing": {"accession_number": "0000320193-26-000006", "form": "10-Q",
                 "period": "2025-12-27", "filed_date": "2026-01-30",
                 "source_url": "https://www.sec.gov/Archives/..."}
    }
  ],
  "proposed_sales": [
    {
      "person_name": "WERNER ROBERT F.",
      "person_cik": "0001590947",
      "relationships": ["Officer"],
      "security_class": "Common",
      "shares": 8275,
      "aggregate_market_value": 860856.53,
      "shares_outstanding": 68178692,
      "approx_sale_date": "2026-11-20",
      "exchange": "NASDAQ",
      "acquired": [{"date": "2026-02-20", "nature": "Restricted Stock Vesting", "shares": 496}],
      "plan_adoption_date": null,
      "filing": {"accession_number": "0001959173-26-008215", "form": "144",
                 "filed_date": "2026-11-23", "source_url": "https://www.sec.gov/Archives/..."},
      "followed_by": {
        "accession_number": "0001415889-26-000001", "form": "4", "filed_date": "2026-11-24",
        "transaction_date": "2026-11-20", "shares": 8275, "average_price": 104.03,
        "source_url": "https://www.sec.gov/Archives/...",
        "match": {"rule": "same_person_cik", "days_after_notice": 0}
      }
    }
  ],
  "labels": {"disclaimer": "Information, not signals. Not investment advice."},
  "notes": ["...the join rule below, in one sentence..."]
}
```

Field rules:
- `action` is `adopted` or `terminated`. `plan_type` is `rule_10b5_1` or `non_rule_10b5_1` (a
  "non-Rule 10b5-1 trading arrangement"). One person can have an adoption and a termination in
  the same filing, which gives two rows. `date` is the adoption or termination date as tagged.
  `duration_days`, `expiration_date` and `shares` (the aggregate securities the plan covers) are
  `null` when the filing does not tag them; they are never inferred.
- A filing that tags only "no plans adopted or terminated" adds no row.
- In `proposed_sales`, values are as given in the notice. `aggregate_market_value` is the filer's
  own estimate on the notice date. `acquired` lists the notice's "securities to be sold" lines
  (at most 20; `acquired_count` gives the full number).
- `plan_adoption_date` is the 10b5-1 plan date the notice gives, when it gives one.

**Join rule (`followed_by`).** A Form 144 notice is joined to one Form 4 that meets all three
conditions:
1. It has the same issuer.
2. It has the same reporting person. The match is by CIK (`same_person_cik`), or, when the notice's
   person has no Form 4 under that CIK at this issuer, by normalized name (`same_person_name`:
   last name plus first initial, case and punctuation ignored).
3. It reports an open-market or private sale (transaction code `S`) of the same class, dated from
   the notice date minus 7 days to the notice date plus 90 days, and it was filed on or after the
   notice.

When several qualify, the first in this order wins (D-12b hand-check, 24 Nov), with ties going to
the earliest sale:
1. a sale within 3 days after the notice's sale date (`approx_sale_date`, or the notice date when
   earlier) of exactly the notice's shares, in all or on one line (daily sellers file a notice and a
   Form 4 of the same size every day);
2. only earlier sales of exactly the notice's shares, filed after the notice (a notice filed late);
3. the same, filed on the notice's day, the last sale at most a day before the sale date;
4. any other Form 4 with a sale on or after the sale date;
5. a Form 4 filed after the notice whose last sale is at most a day before the sale date.

A Form 4 whose sales all predate the sale date otherwise reports an earlier notice's sale and is
never joined.

The notice is valid for three months under Rule 144(h). `days_after_notice` is the Form 4
transaction date minus the notice date. The field is `null` when no Form 4 matches, which is
normal: a notice does not oblige a sale.

`followed_by_status`: `matched`; `no_sale_reported` only when every quarterly Form 4 data set from the notice date to 90 days after it is loaded, and with `as_of` only when those 90 days ended by `as_of` (D-12b: a gap in the loaded quarters or a window past the newest data set is `pending`, never "no sale"); otherwise `pending`.

The sale is a fact; the join is our inference. The ui says so ("Matched by CIK" or "Matched by
name").

Events (timeline and the event stream):
- `sec.trading_plan_adopted` and `sec.trading_plan_terminated`: one event per row, dated by
  the filing date of the 10-Q or 10-K, with the plan date in the payload.
- `sec.proposed_sale`: one event per Form 144, dated by its filing date.

| Status | When |
|---|---|
| 200 | both lists (either may be empty) |
| 404 `company_not_found` | unknown CIK |

MCP: the `insider_plans` tool, `{cik, since?, as_of?}`.
