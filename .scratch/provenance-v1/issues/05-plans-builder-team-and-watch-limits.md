# 05: Builder and Team plans with per-plan watch limits

**What to build:** The plans advertised on the pricing page exist in the API. A key on Builder or Team gets the advertised rate limit, monthly quota, export rows and maximum watched companies; usage reporting shows the plan's limits and current consumption.

**Blocked by:** 01

**Status:** done

- [x] Plans `free`, `builder`, `team`, `enterprise`, `internal` with limits matching the pricing page
- [x] Watch creation enforces the plan's watched-company limit (distinct CIKs) with a clear error
- [x] Usage endpoint reports watch limit and watches used
- [x] Key creation script and admin endpoint accept the new plans; tests cover enforcement
