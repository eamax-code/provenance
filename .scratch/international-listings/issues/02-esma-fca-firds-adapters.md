# 02: ESMA and FCA FIRDS adapters with GLEIF enrichment

**What to build:** A daily job pulls the latest FIRDS delta (and optionally full) files from ESMA and the FCA for configured venues, parses equity instruments into listing records, enriches issuers from GLEIF by LEI, and ingests them; parsers are tested on real sample records.

**Blocked by:** 01

**Status:** ready-for-agent

- [ ] Register file discovery for a date, download with size bounds and caching, XML streaming parser for equity records (new/modified/terminated)
- [ ] Venue registry for covered EU/EEA/UK MICs
- [ ] GLEIF client with rate limiting and fixture-tested parsing; issuer enrichment
- [ ] `scripts/ingest_markets.py`, poller integration, run and snapshot counts
