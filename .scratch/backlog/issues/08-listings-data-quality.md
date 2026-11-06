# 08: Listings data quality: structured products and primary-listing signal

**What to build:** Remove non-share instruments that registers classify as equity (e.g. an XS-ISIN BNP Paribas certificate on Luxembourg), and capture FIRDS `IssrReq` (admission requested by the issuer) so a new listing can be marked as a likely primary listing versus a secondary trading line.

**Blocked by:** None

**Status:** done (2026-11-06)

- [x] Rules for excluding structured products recorded and tested on real records
- [x] `issuer_requested` stored on instruments and exposed; `new_listing` details include it
- [x] Data dictionary and research report updated
