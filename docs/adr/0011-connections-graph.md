# ADR 0011: A company's connections graph from Forms 3/4/5, exhibit 21 and Schedules 13D/G

**Status:** accepted (2026-11-18)

The Explorer had no view of who runs, owns or sits under a company. EDGAR publishes all three
for free and without redistribution limits: insider reports (Forms 3, 4, 5), the list of
significant subsidiaries filed with each 10-K (exhibit 21; exhibit 8 of a 20-F) and beneficial
ownership above 5% (Schedules 13D and 13G). GH #24 asks for ownership data; this is its first
half.

**Decision.**
- **Insiders** come from the SEC's quarterly insider transaction data sets (one ~8 MB file per
  quarter, every Form 3, 4 and 5 as tables), loaded by `scripts/ingest_connections.py`. Forms
  filed after the latest data set are read one by one from their XML, using the accessions the
  `filings` table already holds. Both sources land in `insider_filings` (one row per reporting
  owner per filing) and `insider_transactions` (table I and II rows), replaced per accession so
  reloading is idempotent. Owner street addresses are in the sources and are never stored.
- **Subsidiaries** are parsed from the exhibit of the latest annual report that has one, and of
  the one before it, so the API can say which names are new and which are gone. Tables are read
  first, then lines ("Foo LLC (Delaware)", "Foo Ltd. .... Ireland"). Each row keeps the
  exhibit's URL.
- **5% holders** come from the structured 13D and 13G filings (XML since December 2024) of the
  last three years. A filer's latest schedule is its current stake; one below 5% is shown only
  on request. Free-text schedules from before December 2024 are not read.
- **Board interlocks** need no new source: the other issuers each director and officer files
  Forms 3, 4 or 5 for.
- `GET /v1/companies/{cik}/graph` returns nodes and edges; every edge carries the filing it comes
  from (an EDGAR filing or exhibit URL, never an API URL). `insiders`, `insider-transactions`,
  `subsidiaries` and `holders` return the same data as lists. `as_of` uses only filings made by
  that date. Nodes that are companies in this API carry their CIK so a client can open them.
- Per-company sources are read on demand for keyed callers when older than seven days, in the
  background (`refreshing: true`); never for the demo key, which sees what is stored.

**Consequences.** An insider is "current" when they filed in the last two years; Form 4 has no
end date for a role, so a departed director who never files again turns former after two years
(8-K item 5.02 changes are the faster signal and are a planned join). Exhibit 21 may omit
subsidiaries that are not significant, and its layout varies; the parser is tested on real
exhibits and keeps the source link for every row. Holder percentages are as reported on each
schedule and are not recomputed. `docs/connections.md` lists what the graph can show next.
