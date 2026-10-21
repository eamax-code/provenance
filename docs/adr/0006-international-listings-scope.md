# ADR 0006: International listing lifecycle (Canada, Europe, UK) is in scope

**Status:** accepted (2026-10-22)

AGENTS.md section 2 lists "broad non-US issuer coverage" as out of scope for the MVP. The
owner asked on 2026-10-21 for Canadian and European public-company identity and listing
lifecycle (new listings, IPOs, delistings, suspensions) from direct sources. This ADR records
the deliberate expansion and its boundaries:

- Scope is **identity and listing lifecycle**, not financial statements: ISIN, issuer name
  and LEI, venue (MIC), currency, admission/first-trade/termination dates, status, and the
  events derived from changes. No prices, no XBRL facts for non-US issuers.
- Sources must be **official or exchange-direct, free, and machine-readable**, with their
  redistribution terms recorded in docs/data-rights.md. Regulator registers (ESMA FIRDS,
  FCA FIRDS, GLEIF) are preferred; exchange lists are used only for metadata and only where
  terms allow.
- Every row carries `source`, `source_url`, `first_detected_at` and `last_seen_at`, and
  events are idempotent per (ISIN, MIC, type, date), mirroring the SEC filing rules.
- `new_listing` is never presented as an IPO. An `ipo` event exists only when the source
  states it.
- Rows are keyed by (ISIN, MIC); an issuer with several lines or venues has several rows.

Source adapters are pluggable so a source with unacceptable terms can be disabled without
touching the model.
