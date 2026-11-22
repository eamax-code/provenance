# Chat reply schema (C-01)

`POST /v1/chat` returns a `ChatReply`. Version 2 (2026-11-23) adds `schema_version`, `blocks`
and `how`. Every version-1 field (`answer`, `citations`, `widgets`, `brief`, `notes`, `intent`,
`answered_by`, `context`, `suggestions`) is unchanged, so a version-1 reader keeps working and a
saved version-1 reply (no `schema_version`) still renders: treat a missing `blocks` as
`[{"type": "text", "text": answer}]` plus the `widgets`.

## Fields added in version 2

| Field | Type | Meaning |
|---|---|---|
| `schema_version` | `"2"` | The reply format. Absent on replies saved before version 2. |
| `blocks` | list | The answer in reading order: a `text` block, then `figure` chips, then the tables, charts and stats also in `widgets`. Every reply has at least the text block when it has an answer. |
| `how` | list | "How I got this": the API calls that return the same data, each `{endpoint, parameters, as_of}`. Empty when the answer is not a figure lookup (a refusal, a model answer). |

## Blocks

`text`: `{type, text, citations}`. `citations` lists the citation numbers used in `text`
(each matches an entry in the reply's `citations`, whose `url` is the filing on sec.gov/Archives).

`figure` (a figure chip): every figure a data answer states, with what the provenance card shows.

```json
{
  "type": "figure", "metric": "revenue", "label": "Revenue",
  "value": 391035000000.0, "unit": "USD", "display": "$391.0 billion",
  "period_start": "2023-10-01", "period_end": "2024-09-28",
  "form_type": "10-K", "filed_date": "2024-11-01",
  "accession_number": "0000320193-24-000123",
  "source_url": "https://www.sec.gov/Archives/edgar/data/320193/000032019324000123/0000320193-24-000123-index.htm",
  "source_tag": "RevenueFromContractWithCustomerExcludingAssessedTax",
  "mapping_version": "1.5.0", "quality_status": "ok", "derived": false, "citation": 2
}
```

(Values illustrative.) A margin answer has one chip per input (for an operating margin: operating
income and revenue); the margin itself is derived and stated in the text with both citations.

`table`, `chart`, `stats`: the same objects as in `widgets` (the chat page already draws them).

## How I got this

```json
"how": [{"endpoint": "/v1/companies/320193/facts",
         "parameters": {"metric": "revenue", "period": "annual"}, "as_of": null}]
```

Figures: `/v1/companies/{cik}/facts` with the metric (a margin uses the derived metric, e.g.
`operating_margin`). Compares: one call per company. Rankings: `/v1/facts/screen`. Recent IPOs:
`/v1/ipos`. Calling these with the same `as_of` returns the values the answer used.

## Rules that hold in every version

- A sentence that states a figure cites its filing; a data answer with an uncited money figure is
  withheld (the C-07 eval checks it: `tests/integration/test_chat_eval.py`).
- Figures are in the company's reporting currency; a negative amount reads "−$1.0 million".
- Missing figures are said to be missing, never shown as zero.
