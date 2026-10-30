# 09: Watches and webhooks for listing events

**What to build:** A key holder subscribes to new listings, delistings or suspensions for a venue, country or region and receives signed, deduplicated webhook events, reusing the filing-watch delivery design (international-listings spec, user story 19).

**Blocked by:** 07

**Status:** ready-for-agent

- [ ] Watch model and API for listing scopes; plan limits apply
- [ ] Deliveries created per new event; console shows them; tests
