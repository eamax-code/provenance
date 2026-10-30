# 07: Resolve issuer identity for every listing from GLEIF bulk files

**What to build:** Many listings still show the instrument's register name (e.g. "SERICA ENERGY PLC ORD USD0.10") because GLEIF is queried one LEI at a time (420 per run). Use the daily GLEIF ISIN-LEI mapping and golden-copy delta files (CC0) to resolve every issuer in one pass, and fall back to ISIN-to-LEI where FIRDS lacks an issuer LEI.

**Blocked by:** None

**Status:** ready-for-agent

- [ ] Bulk mapping download (size-capped, cached) and LEI record loading for covered issuers
- [ ] Issuer names, country and status on all listings; per-call lookups only for gaps
- [ ] Tests on trimmed real mapping and golden-copy fixtures
