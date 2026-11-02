# 17: Live event stream (filings and listing events)

**What to build:** One ordered feed of new SEC filings and international listing events. It is available both as a polling endpoint, `GET /v1/events?after=<cursor>`, and as Server-Sent Events, `GET /v1/events/stream`. A client can reconnect with `Last-Event-ID` and loses nothing. Backfill never appears: the same rule as webhooks (ADR 0004) is now stored on each filing.

**Blocked by:** none

**Status:** in-progress

- [ ] `filings.is_backfill` set at ingestion (first ingestion, history pages, older than the notify age); existing rows migrated as backfill
- [ ] Opaque cursor over (detected time, kind, id); stable order across both sources, with no gaps or duplicates when many rows share a timestamp
- [ ] Filters: `types`, `cik`, `form_type`, `mic`, `event_type`; `since` bounded to 30 days
- [ ] SSE: heartbeats, poll interval and maximum connection time from settings, concurrent streams per key limited by plan; the demo key cannot stream
- [ ] Event ids match the cursor, so `Last-Event-ID` resumes exactly
- [ ] Tests for ordering, resume, filters, backfill exclusion, stream limits; docs and playground entry
