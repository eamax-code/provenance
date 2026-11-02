# 17: Live event stream (filings and listing events)

**What to build:** One ordered feed of new SEC filings and international listing events. It is available both as a polling endpoint, `GET /v1/events?after=<cursor>`, and as Server-Sent Events, `GET /v1/events/stream`. A client can reconnect with `Last-Event-ID` and loses nothing. Backfill never appears: the same rule as webhooks (ADR 0004) is now stored on each filing.

**Blocked by:** none

**Status:** done

- [x] `filings.stream_status` set at ingestion (only rows that would notify stream); existing rows migrated as skipped
- [x] Opaque cursor over (detected time, kind, id); stable order across both sources, with no gaps or duplicates when many rows share a timestamp
- [x] Filters: `types`, `cik`, `form_type`, `mic`, `event_type`; `since` bounded to 30 days
- [x] SSE: heartbeats, poll interval and maximum connection time from settings, concurrent streams per key limited by plan; the demo key cannot stream
- [x] Event ids match the cursor, so `Last-Event-ID` resumes exactly
- [x] Tests for ordering, resume, filters, backfill exclusion, stream limits; docs and playground entry
- [x] Ordered by publication time stamped after commit, not detection time (ADR 0007)
