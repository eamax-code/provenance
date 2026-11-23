# D-15 Private raises (Form D)

**Built 2026-11-24**: 8 quarters (2024q4-2026q3), 92,748 offerings. Additive: `related_persons_count`; list parameters `min_sold` (the cumulative amount sold on the latest filing: what was raised) and `order=sold`; chat answers say how far the data sets run. "Raised" always means the amount sold, never the offering size; an amended offering counts once (its latest filing's cumulative amounts); an indefinite offering size is null, never 0.

`GET /v1/companies/{cik}/private-raises?since=&limit=` (one issuer's Form D offerings)
`GET /v1/private-raises?industry=&state=&min_amount=&from=&to=&exemption=&limit=&cursor=`

**Source.** The SEC's structured Form D data sets (quarterly), the last 8 quarters, fetched
internally through our SEC client. Each offering links to its Form D filing on sec.gov/Archives.
Everything is **self-reported by the issuer on Form D; amounts as filed**. A Form D is a notice
of an exempt offering, not a registration: nothing in it is reviewed by the SEC.

One item per offering. An amendment (D/A) is chained to its original by the original's file
number; the item shows the latest filed values, with every filing in `filings`.

```json
{
  "data": [
    {
      "issuer": {"cik": "0001234567", "name": "Example Bio, Inc.", "state": "CA",
                 "jurisdiction": "DELAWARE", "entity_type": "Corporation",
                 "year_of_incorporation": "2019", "is_registrant": false},
      "industry_group": "Biotechnology",
      "total_offering_amount": 60000000, "total_amount_sold": 52000000,
      "total_remaining": 8000000, "indefinite": false,
      "investors": {"total": 14, "non_accredited": 0},
      "first_sale_date": "2026-09-03", "first_sale_yet_to_occur": false,
      "exemptions": ["06b"],
      "minimum_investment": 250000,
      "sales_commissions": 0, "finders_fees": 0,
      "related_persons": [{"name": "Jane Doe", "relationships": ["Executive Officer", "Director"],
                           "city": "San Francisco", "state": "CA"}],
      "latest_filing": {"accession_number": "...", "form": "D/A", "filed_date": "2026-10-01",
                        "source_url": "https://www.sec.gov/Archives/..."},
      "filings": [{"accession_number": "...", "form": "D", "filed_date": "2026-09-10",
                   "source_url": "https://www.sec.gov/Archives/..."}]
    }
  ],
  "meta": {"limit": 50, "has_more": true, "next_cursor": "..."},
  "labels": {"basis": "Self-reported by the issuer on Form D; amounts as filed."},
  "notes": ["Exemption codes as filed: 06b = Rule 506(b), 06c = Rule 506(c), 04 = Section 4(a)(5), 3C.1-3C.7 = Investment Company Act exclusions."]
}
```

Rules:
- `exemptions` are the codes as filed, explained in `notes`.
- `industry_group` is the Form D industry group as filed, such as "Biotechnology", "Pooled Investment Fund" or "Other Technology".
- `related_persons` are as filed, at most 10 per offering with `related_persons_count` for the rest. They are **not** linked to our officer graph: exact-name links across issuers are not safe (TODO).
- `is_registrant` is true when the issuer's CIK also files periodic reports (10-K, 10-Q, 20-F) with us.
- Amounts are US dollars as filed. `indefinite` is true when the offering amount is "Indefinite", in which case `total_offering_amount` is null.
- **List filters:**
  - `industry` is an industry group as filed (case-insensitive);
  - `state` is the issuer's state or country code;
  - `min_amount` applies to the total offering amount, or to the amount sold when the offering is indefinite;
  - `from` and `to` apply to the latest filing date;
  - `exemption` is one code.
  - Sorted newest first.
- The demo key's 10-row cap applies.

| Status | When |
|---|---|
| 200 | items (may be empty) |
| 404 `company_not_found` | unknown CIK (company route) |
| 422 `invalid_parameter` | a bad filter |

Chat: "Who raised over $50M in biotech last quarter?" answers from the list, with each issuer cited to its Form D. MCP: the `private_raises` tool, with the list's filters, or a cik.
