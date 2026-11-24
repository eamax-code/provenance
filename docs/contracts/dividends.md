# Q-04 Dividends: declared per share by period, payout ratio, special dividends, splits

Status: **contract** (2026-11-25, for provenance-ui). Nothing is built yet; fields marked
*provisional* may still be renamed before they are, and ui is told when they are.

`GET /v1/companies/{cik}/dividends?period=&periods=&as_of=&basis=`

Dividends declared on common stock, per share, as each company reports them in its 10-K and
10-Q XBRL, each value with the filing it comes from. Information about what companies reported,
not signals. **No yield** until end-of-day prices exist (P-01).

## Source and coverage

- Per-share values come from the company's own XBRL: `CommonStockDividendsPerShareDeclared`,
  else `CommonStockDividendsPerShareCashPaid` (then `basis_tag` says "cash paid"). IFRS filers:
  the per-share dividend tag they use, in their own currency.
- These tags are not stored today. Loading them is a mapping addition (a new metric,
  `dividends_per_share`) and a re-read of each company's facts: dry run first, the count of
  companies and periods reported with it, then the 30-period hand-check below.
- `dividends_paid` (the cash-flow total already stored) is shown beside each period, as stored.
- A company that reports no per-share dividend tag gets `200` with `data: []` and a note, never
  zeros: no dividend reported is not the same as no dividend paid.
- Values are as reported, in the reporting currency (`unit`, e.g. `USD/shares`, `JPY/shares`);
  nothing is converted.

## Parameters

| Parameter | Values | Default |
|---|---|---|
| `period` | `annual` or `quarterly` | `annual` |
| `periods` | 1-20 annual, 1-80 quarterly | 10 annual, 20 quarterly |
| `as_of` | ISO date: only filings made by then | none |
| `basis` | `as_reported` or `split_adjusted` (which value fills `value`; both are always given) | `as_reported` |

## Response

```json
{
  "cik": "0000909832",
  "period": "annual",
  "as_of": null,
  "currency": "USD",
  "data": [
    {
      "period_label": "FY2024",
      "period_start": "2023-09-04",
      "period_end": "2024-09-01",
      "declared_per_share": 19.40,
      "unit": "USD/shares",
      "basis_tag": "declared",
      "derived": false,
      "filing": {"accession_number": "0000909832-24-000049", "form": "10-K",
                 "filed_date": "2024-10-09",
                 "source_url": "https://www.sec.gov/Archives/edgar/data/909832/..."},
      "split_adjusted": {"value": 19.40, "factor": 1, "derived": true},
      "special": {"likely": true, "amount_above_regular": 15.00, "derived": true,
                  "basis": "..."},
      "payout_ratio": {"value": 1.15, "derived": true, "basis": "declared per share / diluted EPS",
                       "inputs": [{"metric": "eps_diluted", "value": 16.56,
                                   "accession_number": "...", "source_url": "..."}]},
      "dividends_paid": {"value": 8595000000, "unit": "USD", "accession_number": "...",
                         "source_url": "..."}
    }
  ],
  "splits": [{"ratio": "4:1", "date": "2020-08-28", "source": {"form": "8-K", "filed_date": "...",
              "evidence": "..."}}],
  "labels": {"basis_note": "As reported: each value in the share basis of the filing it cites."},
  "notes": ["..."]
}
```

### Field rules

- **One value per period:** the latest filing (by `as_of`) that reports it; a later 10-K that
  restates a year (after a split) wins, as on the statements.
- **Quarterly** values are as reported. A Q4 is **derived** (FY minus the first three quarters,
  `derived: true` with its inputs) only when all four values sit on one share basis (no reviewed
  split between the filings they cite); otherwise the Q4 is `null` with a note. Per-share
  dividends add up over a year, unlike EPS, but only on one share basis.
- **`split_adjusted`** puts every value on the share basis of today, using only the reviewed
  split list (`app/data/splits_reviewed.csv`) and the statements' rule: a value cited from a
  filing made before a split's effective date is divided by that split's ratio (compounded across
  splits); one made after is unchanged. `factor` is the divisor applied. A value filed within a
  split given only to the month has `split_adjusted: null`. `splits` lists the reviewed splits
  used, each with its filing quote. The as-reported value always stays beside it; headers say
  "as reported" or "split-adjusted".
- **`special`** (*provisional*; derived): company facts do not mark special dividends (Costco's
  $15.00 of December 2023 is inside its FY2024 total). A quarter is `likely: true` when its
  declared amount is at least 2.5 times the median of the company's other declared quarters in
  the two years around it (four or more such quarters, on one share basis); `amount_above_regular`
  is the excess over that median. An annual period is `likely` when one of its quarters is. Fewer
  than four quarters to compare: `special: null`. The basis text says it is a reading of the
  amounts, not the company's label, and the gate reports how many flags are right.
- **`payout_ratio`** (derived, annual only): declared dividends per share divided by diluted EPS
  for the same fiscal year, both as reported in the same period and share basis. `null` when EPS
  is zero or negative, missing, or in another currency. Over 1.0 is possible (paying more than
  earned) and shown as it is. Quarterly views give `payout_ratio: null`.
- `dividends_paid` is the cash-flow line for the period as stored (all classes, including
  preferred where a company reports one total), so it does not reconcile with per share times
  shares and is never used to derive anything here.
- Links are sec.gov/Archives filing pages only. No API URLs, no fetch or detection times.

## Errors and access

- `404 company_not_found`; `422 invalid_parameter` for a bad period, periods or basis.
- The demo key: showcase companies only, at most 10 periods, trimmed with a note.
- Usual rate and plan limits.

## MCP and chat (after the API)

- MCP tool `company_dividends` with the same parameters.
- Chat answers "what dividend does Costco pay", "Apple's dividend history" with the rows, each
  linked to its filing, "as reported" or "split-adjusted" in the header, never a yield.

## Gate before release

- Load: dry run of the mapping addition, with the count of companies and periods per tag and per
  currency.
- Hand-check 30 periods against the filings (at most 1 wrong): including a company with a
  reviewed split (Apple or NVIDIA; split-adjusted values), a special dividend (Costco FY2024 and
  its quarter), a non-USD filer (Toyota, JPY), a derived Q4, and a company that reports cash paid
  only. The special flag is checked separately on every flag in a random 30 companies (how many
  are real specials, how many specials it misses), and the result decides whether it ships.
- R-2: p95 under 500 ms for annual and quarterly, both bases.
