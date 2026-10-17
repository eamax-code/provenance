# 07: Developer console

**What to build:** From the same app a developer manages their account: sees usage over time by route, current plan limits, lists and revokes keys, creates and deactivates watches, and inspects delivery attempts with status and redacted errors. Webhook secrets are shown once with verification instructions.

**Blocked by:** 05, 06

**Status:** done

- [x] Usage view with totals, by-route breakdown, export rows/bytes and plan limits
- [x] Keys list and revoke with confirmation built into the page
- [x] Watch create (webhook/email), list, deactivate; deliveries list per watch
- [x] Console works against the live API in integration tests of the backing endpoints; UI syntax-checked in CI
