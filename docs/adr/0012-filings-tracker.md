# ADR 0012: Read every EDGAR filing each hour; track companies going public

**Status:** accepted (2026-11-19)

Anthropic, PBC priced its IPO on 2026-11-19 (424B4), a day after its registration went effective
and eight insiders filed Forms 3. The local copy had it only through 2026-11-12. Nothing read
EDGAR between bulk loads: the poller refreshes companies already in the universe on a six-hour
cycle and never learns that a new company has filed. Going public is the moment users care most
about.

**Decision.**
- A filings tracker runs every hour inside the poller (`FILINGS_TRACKER_INTERVAL_SECONDS`, 3600)
  and from `scripts/track_filings.py`. It reads three public EDGAR indexes into `edgar_feed`, one
  row per filing per company it names:
  - **full-text search** for today's and yesterday's going-public forms (S-1, F-1, 424B4, 8-A,
    Form 10, DRS, RW), then 10-K, 10-Q, 20-F, 40-F, 8-K and 6-K. It answers in under a second and
    holds a filing within minutes, but is not complete for Forms 3, 4 and 5;
  - the **latest-filings feed**, every form, paged until a page brings nothing new. It is often
    slow (20-second timeouts were seen on the first day), so it gets one retry and a failure ends
    the read for that run;
  - the **daily index**, once per day after it is published, as the complete record. Whatever the
    other two missed is filled the next day.
- Acting on the rows, oldest first, at most `FILINGS_TRACKER_MAX_COMPANIES` (1,500) per run:
  - a covered company is refreshed: filings (no history pages), XBRL facts after a periodic
    report, Forms 3/4/5 after an insider filing. New filings reach the event feed and watch
    notifications as any poll does;
  - a company not covered is **added** when a filing shows a public company or one going public
    (S-1, F-1, 424B4, 8-A, Form 10, 10-K, 10-Q, 20-F, 40-F). Funds and exchange-traded products
    are skipped: they file 485/497/N- forms, or list a class on 8-A under a fund or trust name. Its
    filings the tracker saw go to the event feed; its history does not (ADR 0004);
  - everything else (private placements on Form D, fund filings, people's own filings) is kept
    as a row and left alone.
- `GET /v1/ipos` (and the MCP tool `companies_going_public`) turns the filings of first-time
  registrants into stages: confidential (DRS), filed (S-1, F-1, Form 10), amended, effective
  (EFFECT), listing (8-A12B/G, CERT), priced (424B4), withdrawn (RW). A company that filed a
  10-K, 10-Q, 20-F or 40-F before registering is not going public and is left out. Each milestone
  links its filing.

**Consequences.** A filing reaches the API within about an hour. A day's filings cost about 30
full-text search requests, a few feed pages each hour, one daily index, and one or two requests
per company refreshed, all paced under ten a second. `edgar_feed` grows by about 5,000 rows a
business day; the retention purge can drop handled rows older than a year. Coverage now grows by
itself as companies go public. Stages come from filing types only: a 424B4 after a registration
means priced, not that trading has started; the ticker appears when the SEC lists one.
