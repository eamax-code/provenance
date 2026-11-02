# ADR 0007: Event feed orders by publication time, not detection time

**Status:** accepted (2026-11-03)

The event feed (`GET /v1/events`, `GET /v1/events/stream`) merges new SEC filings and
international listing events into one ordered, resumable sequence. A client holds an opaque
cursor and must never miss or repeat an event.

**Problem.** Ingestion stamps `first_detected_at` / `detected_at` when a run starts and commits
when it ends. A FIRDS file can take minutes. A reader that has already moved past time T would
never see rows stamped T that commit later. Database sequences have the same flaw: numbers are
assigned at insert, not at commit.

**Decision.**
- New feed rows are written with `stream_status = 'pending'`. After the ingesting transaction
  commits, `publish_pending` stamps them `published` with `stream_at = now` in a short separate
  transaction. The poller runs the same sweep each cycle, so rows left pending by a crash are
  published later.
- Readers see only rows with `stream_at <= now - EVENTS_SETTLE_SECONDS` (default 5 s). That
  margin covers the gap between taking `now` and committing the publish statement.
- Order is `(stream_at, kind, id)`; the cursor encodes that triple. Paging uses keyset
  conditions per kind, so many rows sharing one `stream_at` page without gaps or duplicates.
- After a page that is not full, the cursor advances to the end of the settled window, so idle
  polls stay cheap. SSE sends that cursor as an id-only block, which moves the client's
  `Last-Event-ID` forward without firing an event.
- Backfill never streams (same rule as ADR 0004): filings default to `skipped` and only the
  rows that would notify become `pending`. Listing events that existed before the feed were
  migrated as published at their detection time.

**Consequences.** Events reach the feed a few seconds after commit. `stream_at` is our
publication time, not the source's; the source and detection times stay in `data`. Concurrent
stream limits are per process until the multi-replica work in ticket 12.
