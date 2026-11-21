# Provenance for Google Sheets

Two custom functions put reported figures, and the SEC filing behind them, into any cell.

```
=PROVENANCE("AAPL", "revenue")                    latest annual revenue
=PROVENANCE("AAPL", "revenue", "FY2024")          one fiscal year
=PROVENANCE("320193", "net_income", "Q2 FY2026")  one fiscal quarter
=PROVENANCE("MSFT", "operating_income", "CY2025") one calendar year, so companies line up
=PROVENANCE_SOURCE("AAPL", "revenue", "FY2024")   the filing on sec.gov behind that value
```

- **Company:** a ticker, a CIK or a name.
- **Metric:** any metric name from the API, such as `revenue`, `net_income`, `total_assets`, `eps_diluted` or `gross_margin`.
- **Period:** optional. Accepted values:
  - `latest` (the default)
  - `latest quarter`
  - `FY2024` (or just `2024`)
  - `Q2 FY2026`
  - `CY2025` or `CY2025Q4`

A period with no filed value returns `not reported`, never 0. Ratios such as `gross_margin` come back in percent. Every number comes from Provenance's API, with the same mapping and quality rules.

## Install

1. In your sheet, open **Extensions > Apps Script**.
2. Replace the contents of `Code.gs` with [`Code.gs`](Code.gs) from this folder, and save.
3. Open **Project settings > Script properties** and add:
   - `PROVENANCE_API_KEY`: your key, from the account page (`/account/`). A free key covers every company.
   - `PROVENANCE_BASE_URL`: the API address, for example `https://api.example.com`.
4. Back in the sheet, type `=PROVENANCE("AAPL", "revenue")`. The first call asks you to authorise the script to fetch from the API.

The key is stored in the script's properties, not in the sheet, so sharing the sheet does not share the key. Values are cached for six hours. Every call counts against your plan's requests, just as a call made from code does.

## Test outside Google

`test/run.mjs` runs `Code.gs` in Node, with Apps Script's services stood in. It checks each period form against a running server:

```
PROVENANCE_BASE_URL=http://127.0.0.1:8000 PROVENANCE_API_KEY=... node clients/sheets/test/run.mjs
```

Data comes from SEC EDGAR. Provenance is independent and not affiliated with the SEC. Not investment advice.
