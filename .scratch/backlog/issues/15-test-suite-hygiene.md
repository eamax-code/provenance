# 15: Test-suite hygiene

**What to build:** Clear the two remaining warnings (Starlette TestClient deprecation of httpx; a datetime adapter warning) so new warnings stand out, and keep the date-independent test style (the daily-job test once failed when the calendar moved on).

**Blocked by:** None

**Status:** ready-for-agent

- [ ] Zero warnings in `pytest -q`; no test depends on today's date
