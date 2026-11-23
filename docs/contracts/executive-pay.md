# D-10 Executive pay and pay versus performance

`GET /v1/companies/{cik}/executive-pay?as_of=`

**Source.** The pay-versus-performance table (Item 402(v) of Regulation S-K) is tagged in the
proxy's inline XBRL (the `ecd` taxonomy). The SEC's Financial Statement and Notes data sets carry
DEF 14A filings with these tags, so this data comes from the monthly data sets we already load,
with no per-filing fetch. Each proxy covers up to five fiscal years. Each year is shown from the
**latest proxy filed by `as_of`** that reports it, and every figure links to that proxy.

**Scope.** The pay-versus-performance table covers the PEO (principal executive officer, usually
the CEO) and the **average** of the other named executive officers (NEOs). The Summary
Compensation Table, with each NEO's own figures, is **not XBRL-tagged**, so it is not part of
this endpoint. The ui pay table shows the PEO and the NEO average, not one row per NEO.
Smaller reporting companies give three years and no peer TSR or company-selected measure, so
those fields are `null`.

```json
{
  "cik": "0000320193",
  "as_of": null,
  "currency": "USD",
  "proxy": {"accession_number": "0001308179-26-000008", "form": "DEF 14A",
            "filed_date": "2026-01-08", "source_url": "https://www.sec.gov/Archives/..."},
  "years": [
    {
      "fiscal_year_end": "2025-09-30",
      "peo": [{"name": "Mr. Cook", "total_comp": 74294811, "comp_actually_paid": 108421987}],
      "neo_average": {"total_comp": 27000000, "comp_actually_paid": 30000000,
                      "names": ["Deirdre OBrien", "Sabih Khan", "Kevan Parekh", "Luca Maestri",
                                "Kate Adams"]},
      "tsr": 220.75,
      "peer_tsr": 210.12,
      "net_income": 112010000000,
      "company_selected_measure": {"name": "Net Sales", "value": 416161000000},
      "source": {"accession_number": "0001308179-26-000008", "filed_date": "2026-01-08",
                 "source_url": "https://www.sec.gov/Archives/..."}
    }
  ],
  "measures": ["Net Sales", "Operating Income", "Relative TSR"],
  "labels": {"disclaimer": "Information, not signals. Not investment advice.",
             "basis": "As disclosed in the proxy."},
  "notes": ["Compensation actually paid is the SEC's defined measure (Item 402(v)), not realized pay.",
            "TSR is the value at year end of $100 invested at the start of the first year shown."]
}
```

(The figures above show the shape only; they are not checked values.)

Field rules:
- `years` is newest first, one entry per fiscal year-end date (`ddate` of the tagged fact).
- `peo` has more than one entry in a year when the company had two PEOs (tagged per individual).
  Each entry has its own `total_comp` (the Summary Compensation Table total, as the proxy
  restates it) and `comp_actually_paid`. When the proxy tags a single untagged-individual PEO
  value, `name` comes from `ecd:PeoName`, or is `null` when that tag is absent.
- `tsr`, `peer_tsr`, `net_income` and `company_selected_measure.value` are exactly as tagged,
  with nothing recomputed or converted. `currency` is the proxy's monetary unit. A mix of units
  in one proxy is reported per value (`unit`) and never summed.
- `measures` is the proxy's tabular list of most important measures (`ecd:MeasureName`).
- `source` on each year is the proxy that year is taken from. It is a different proxy from the
  top-level `proxy` (the latest) only when an older year no longer appears in the latest one.

| Status | When |
|---|---|
| 200 | the table; `years: []` when no proxy with a tagged table was filed by `as_of` |
| 404 `company_not_found` | unknown CIK |

Events: none in this window. MCP: the `executive_pay` tool, `{cik, as_of?}`, with the same
payload.
