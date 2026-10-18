# ADR 0004: A company's first ingestion creates no notification events

**Status:** accepted (2026-10-17)

Filings discovered while a company is ingested for the first time (backfill of ~1,000 recent
filings) do not fan out to watches. Neither do filings that arrive from older-filings history
pages, nor filings whose `filing_date` is older than `NOTIFY_MAX_FILING_AGE_DAYS` (default 30)
when first detected. Only recent filings first detected on later runs notify.

Amended 2026-10-18: the history-page and age guards were added after review showed that
enabling `SEC_FILINGS_HISTORY_PAGES` later would have treated a thousand old filings as new.

**Why:** a watch created on a never-ingested company would otherwise receive hundreds of historical events.
