# 02: Landing page renders pricing, sample response and showcase from the API

**What to build:** The landing page's pricing table, hero sample response and a new "Live data" grid come from the public API, with the existing static content as the fallback when the API is unreachable and an honest empty state when nothing is ingested.

**Blocked by:** 01

**Status:** done

- [x] Pricing cards and the compare table re-render from `/v1/public/plans`
- [x] Hero sample response shows a real latest annual revenue fact with its SEC link, labelled as live; falls back to the illustrative sample
- [x] "Live data" grid lists showcase companies with latest filing and latest annual revenue, linking to `/companies/{cik}`
- [x] Served-page test asserts the wiring; site scripts pass the CI syntax check
