# 06: Explorer web app

**What to build:** A developer opens `/app/`, pastes their API key (kept only in their browser), searches a company by ticker, CIK or name, and sees its profile, recent filings with SEC links, normalized facts as a chart and table with provenance, and the freshness panel. Companies not yet ingested show the processing state and refresh automatically.

**Blocked by:** 01

**Status:** done

- [x] Static, framework-free app served by the API with the same visual language as the landing page, both themes, phone width
- [x] Key entry with validation against `/v1/developer/usage`; key stored in localStorage only; clear sign-out
- [x] Search, profile, filings (filters), facts (metric/period toggles, derived toggle, chart + table with source links), freshness
- [x] Error envelope and rate-limit responses surface as readable messages
- [x] Served-file tests plus a JS syntax check in CI
