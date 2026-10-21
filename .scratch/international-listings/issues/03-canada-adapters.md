# 03: Canadian exchange adapters

**What to build:** Canadian venues (TSX, TSXV, CSE, Cboe Canada as permitted by their terms) feed identity and lifecycle records, including exchange-stated IPOs and delistings, through adapters that are disabled until the operator accepts the source terms.

**Blocked by:** 01

**Status:** ready-for-agent

- [ ] Adapters for the sources the research pass approved, each with a fixture test and documented terms
- [ ] Explicit IPO and delisting events from exchange notices where available
- [ ] Settings flags per source; data-rights entries
