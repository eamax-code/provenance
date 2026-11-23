# X-14 What changed in this 10-K

`GET /v1/filings/{accession}/changes`
`GET /v1/companies/{cik}/changes?as_of=` (the latest annual report filed by `as_of`)

Compares a 10-K's **risk factors** (Item 1A) and **MD&A** (Item 7) with the company's previous
10-K, heading by heading.

**Source.** Our stored sections do not hold 10-K items. Item 1A and Item 7 are read from each
10-K's primary document through our SEC client, once, and stored as sections (`10k:1A`, `10k:7`)
for the companies in the read set (the showcase companies first, then the largest filers). A 10-K
outside the read set returns `404 changes_not_available`.

```json
{
  "filing": {"accession_number": "0000320193-25-000079", "form": "10-K", "period": "2025-09-27",
             "filed_date": "2025-10-31", "source_url": "https://www.sec.gov/Archives/..."},
  "prior": {"accession_number": "0000320193-24-000123", "form": "10-K", "period": "2024-09-28",
            "filed_date": "2024-11-01", "source_url": "https://www.sec.gov/Archives/..."},
  "risk_factors": {
    "counts": {"now": 52, "before": 50, "added": 3, "removed": 1, "reworded": 4, "unchanged": 45},
    "added": [{"heading": "The Company is subject to ...", "text": "first 1,500 characters",
               "text_length": 4210, "group": "Legal and Regulatory Compliance Risks"}],
    "removed": [{"heading": "...", "text": "...", "text_length": 1800, "group": "..."}],
    "reworded": [{"heading": "...", "heading_before": "...", "similarity": 0.71,
                  "text": "...", "text_before": "..."}]
  },
  "mdna": {"counts": {"now": 18, "before": 17, "added": 2, "removed": 1, "reworded": 1,
                      "unchanged": 14},
           "added": [], "removed": [], "reworded": []},
  "method": {
    "headings": "Risk factor headings are the bold or italic lead sentences in Item 1A; MD&A headings are its sub-headings.",
    "matching": "A heading is unchanged when its normalized text is identical. Otherwise it is paired with the most similar heading on the other side; a pair at or above 0.60 similarity (token-set Jaccard of heading plus first 400 characters of text) is reworded, and anything left unpaired is added or removed.",
    "threshold": 0.6
  }
}
```

Rules:
- `prior` is the company's previous 10-K, or 10-K/A when it is a full amendment, with a period
  end 9 to 15 months earlier. When none is stored, the response has `prior: null` and lists the
  headings with no diff.
- Texts are trimmed to 1,500 characters; `text_length` gives the full length. The full section is
  at the filing link.
- Headings are as written. Whitespace, numbering and trailing punctuation are ignored for
  matching, not for display.
- A 10-K whose Item 1A says only "not required for smaller reporting companies" gives
  `risk_factors: null` and the note `"not_required"`.
- `reworded` items are sorted by similarity, lowest first, so the largest rewrites come first.
- Also accepted: 20-F (Item 3.D, Item 5) and 10-K/A with full items. A 10-Q compares only its
  Part II Item 1A against the previous 10-Q when that item is present.

| Status | When |
|---|---|
| 200 | the comparison |
| 404 `filing_not_found` | unknown accession |
| 404 `changes_not_available` | not in the read set yet, or not an annual report (`reason` says which) |

MCP: the `filing_changes` tool, `{cik}` or `{accession}`, with texts trimmed to 400 characters.
