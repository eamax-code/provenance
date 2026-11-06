# 07: Resolve issuer identity for every listing from GLEIF bulk files

**What to build:** Many listings still show the instrument's register name (e.g. "SERICA ENERGY PLC ORD USD0.10") because GLEIF is queried one LEI at a time (420 per run). Use the daily GLEIF ISIN-LEI mapping and golden-copy delta files (CC0) to resolve every issuer in one pass, and fall back to ISIN-to-LEI where FIRDS lacks an issuer LEI.

**Blocked by:** None

**Status:** done (2026-11-06)

- [x] Bulk mapping download (size-capped, cached) and LEI record loading for covered issuers
- [x] Issuer names, country and status on all listings; per-call lookups only for gaps
- [x] Tests on trimmed real mapping and golden-copy fixtures

**Done differently:** GLEIF's batch filter (`filter[lei]=a,b,…`, 200 a call) resolves every issuer
in one pass (4,287 issuers in 22 calls, 32 s, on 2026-11-06), so the full golden copy (hundreds of
MB) is not downloaded; records older than 30 days are re-read instead of applying golden-copy
deltas. The daily ISIN-LEI file fills issuer LEIs the register lacks.
