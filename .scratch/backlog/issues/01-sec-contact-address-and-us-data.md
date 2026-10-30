# 01: Provide a personal SEC contact address and load all US public companies

**What to build:** The SEC requires a contact address in every request's User-Agent. Once the owner supplies a personal mailbox (never the work address), load every XBRL filer from the nightly bulk archives so US company pages, the showcase, the playground's US endpoints and the cross-company screen show real data.

**Blocked by:** None

**Status:** ready-for-human (owner supplies the address), then ready-for-agent

- [ ] Owner provides a monitored personal mailbox for `SEC_USER_AGENT`
- [ ] `scripts/import_tickers.py`, `scripts/sec_bulk.py --download`, `--scope facts --dry-run`, then `--scope facts`
- [ ] `SEC_LIVE_TESTS=1` smoke test passes (closes provenance-v1 ticket 09, first criterion)
- [ ] Disk and database size recorded before and after; showcase and playground verified with US data
