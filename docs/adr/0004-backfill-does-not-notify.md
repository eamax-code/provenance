# ADR 0004: A company's first ingestion creates no notification events

**Status:** accepted (2026-10-17)

Filings discovered while a company is ingested for the first time (backfill of ~1,000 recent
filings) do not fan out to watches. Only filings first detected on later runs do.

**Why:** a watch created on a never-ingested company would otherwise receive hundreds of historical events.
