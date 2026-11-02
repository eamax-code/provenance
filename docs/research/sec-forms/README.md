# SEC form intelligence (2026-11-03)

Every form type filed by or about Apple, Microsoft, Alphabet (and pre-2015 Google), Netflix, Berkshire Hathaway and Amazon, read by nine analyst agents (one per form family) under `BRIEF.md`.

- `union.json`: the 97 candidate form codes per company, taken from the EDGAR submissions JSON. This is a lead list.
- `01_periodic.json` … `09_correspondence.json`: one entry per form (70 entries). Each entry has a plain-English description, the companies verified on EDGAR's per-form lists with their latest accession, machine-readable fields, cited findings (company, executives, growth, signals, financial intelligence), product ideas and a sellable suggestion.

Every finding has a `url` and usually a short quote. `source_method` is `xbrl` or `xml` for structured data and `text-summary` for text read through a summarising fetch tool, because no SEC contact email was configured. Re-parse anything before selling it.

Manager spot-checks matched the filings exactly in 5 of 5 cases:
- the Apple CEO transition 8-K
- the Netflix $2.8B termination fee
- the Berkshire DaVita Form 4
- the Alphabet 13F SpaceX row
- the Apple pay-versus-performance XBRL
