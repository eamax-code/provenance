# D-14 Corporate tree

`GET /v1/companies/{cik}/corporate-tree?children_limit=&subsidiaries_limit=`

**Sources.**
- The parents and the GLEIF children come from **GLEIF Level 2** (relationship records and
  reporting exceptions, from the GLEIF golden copy, CC0). GLEIF is named as the source but not
  linked.
- The subsidiaries come from the company's latest **exhibit 21** (the list of subsidiaries in
  its annual report), which we already store. Each links to its filing.
- The company's own LEI is the one we already matched (`company.lei`, with how it was matched).

```json
{
  "cik": "0000019617",
  "entity": {"lei": "8I5DZWZKVSZI1NUHU748", "name": "JPMorgan Chase & Co.",
             "jurisdiction": "US-DE", "lei_match": "name_and_jurisdiction"},
  "parents": {
    "direct": null,
    "ultimate": null,
    "exceptions": [{"kind": "direct", "reason": "NO_KNOWN_PERSON",
                    "text": "No parent: the entity is not consolidated by another entity (no known person)."}]
  },
  "children": {
    "total": 412,
    "data": [{"lei": "7H6GLXDRUGQFU57RNE97", "name": "JPMorgan Chase Bank, National Association",
              "jurisdiction": "US", "relationship": "direct", "status": "ACTIVE",
              "cik": "0000732712"}]
  },
  "subsidiaries": {
    "total": 160,
    "filing": {"accession_number": "...", "form": "10-K", "filed_date": "2026-02-14",
               "source_url": "https://www.sec.gov/Archives/..."},
    "data": [{"name": "JPMorgan Chase Bank, National Association", "jurisdiction": "United States",
              "lei": "7H6GLXDRUGQFU57RNE97", "lei_match": "exact_name_and_jurisdiction"}]
  },
  "notes": ["Parents and GLEIF children are from GLEIF Level 2 relationship data (CC0) as the
            entities report them; subsidiaries are as listed in exhibit 21."]
}
```

(The values above show the shape only.)

Rules:
- `parents.direct` and `parents.ultimate` are each `{lei, name, jurisdiction, status,
  relationship_status, period_start}`, or `null`.
  - When GLEIF records a **reporting exception** instead of a parent, it is listed in
    `exceptions`, with GLEIF's reason code as given and a plain-English `text`. The reason codes
    are `NATURAL_PERSONS`, `NON_CONSOLIDATING`, `NO_KNOWN_PERSON`, `NON_PUBLIC` and
    `BINDING_LEGAL_COMMITMENTS`, among others. A missing parent with no exception is shown as
    "not reported".
  - When the ultimate parent is the same entity as the direct parent, both are given.
- `children` are the entities whose direct or ultimate accounting parent in GLEIF is this
  company's LEI. `relationship` is `direct` or `ultimate_only`. They are sorted with direct
  children first, then by name, and paged by `children_limit` (1-500, default 100).
  - `cik` is set when the child's LEI is matched to an SEC filer.
- `subsidiaries` come from the latest exhibit 21 only.
  - `lei` is filled **only** when one GLEIF entity has exactly the same normalized legal name
    and the same jurisdiction (the exhibit's state or country mapped to ISO codes). Otherwise it
    is `null`; a doubtful link is worse than none.
  - Paged by `subsidiaries_limit` (1-1000, default 200). The ui folds trees over 50 nodes.
- Every node has `lei` or a name, never a GLEIF URL.

| Status | When |
|---|---|
| 200 | the tree. Without an LEI: `entity.lei: null`, `parents` and `children` empty, subsidiaries still given |
| 404 `company_not_found` | unknown CIK |

MCP: the `corporate_tree` tool, `{cik}`, with the lists capped at 50.
