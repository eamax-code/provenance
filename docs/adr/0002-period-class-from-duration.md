# ADR 0002: Period class comes from reported dates, not the SEC fp label

**Status:** accepted (2026-10-17)

Duration facts are classified by day count: annual 350-380, quarterly 80-100, ytd 160-290, else other.
Instant facts are classified by form type. The SEC `fp` label is stored but never used for classification.

**Why:** SEC company-facts labels a 6-month year-to-date value `fp=Q2`. Presenting it as a quarter
would misstate the issuer's numbers.
