# 20: Officer-change analysis from 8-K Item 5.02 (evidence, not signals)

**What to build:** When a company files an 8-K with Item 5.02 (an officer or director departs or is appointed), extract who, which role, appointed or departed, the effective date, any stated reason or "disagreement", and the interim or successor. Each field quotes the filing text it came from. Add context computed from point-in-time facts: revenue and margin growth during the officer's tenure compared with the years before and with SIC peers. Publish it on the event feed within minutes of the SEC accepting the filing. An LLM only extracts and explains; every number comes from stored facts and every claim links to a filing.

**Blocked by:** 01 (live EDGAR polling needs the SEC contact address); owner decisions below.

**Status:** built (2026-11-06); waiting on the owner's framing decision before any score

Research (2026-11-03): no free news API allows commercial use (NewsAPI, GNews, Finnhub, Alpha Vantage, Marketaux, Polygon/Massive and Tiingo free tiers are personal or non-commercial). PR Newswire and Business Wire forbid redistribution and data mining. Google News and Yahoo forbid automated commercial use. GDELT allows commercial use but gives headlines, URLs and tone only, with no article text. SEC EDGAR is free and redistributable; an 8-K appeared in the latest-filings feed about 2 minutes after acceptance. Item 5.02 must be filed within four business days.

- [ ] Owner: confirm framing as evidence-backed event records, not buy/sell signals (US publisher exclusion; get Indian counsel's view on SEBI research-analyst and investment-adviser rules)
- [x] Owner: LLM provider and monthly budget (local Ollama qwen3:4b-instruct, no API cost)
- [x] Store 8-K `items` on filings
- [x] `items=` filter on `/v1/events`
- [x] Poll EDGAR latest-filings (8-K) every 30-60 s within fair-access limits
- [x] Extraction with verbatim evidence spans (each span traced to a filing sentence); unverified rows marked (`app/services/officer_changes.py`, tables `filing_sections`, `officer_changes`)
- [x] Tenure context from point-in-time facts; peer comparison by SIC
- [x] Before any score or weighting: backtest historical 5.02 events with `as_of` to measure base rates, and publish base rates instead of hand-set weights
- [ ] Optional: GDELT headline links as corroboration (metadata only, with attribution)

**Built 2026-11-06.**
- Event feed: filing events carry their 8-K `items`; `items=5.02` filters; officer changes are
  `sec.officer_change` events (`types=leadership`), published when read, with evidence and
  `verified`. Readings made before this never stream.
- `scripts/poll_current_8k.py`: EDGAR's latest-filings Atom feed every 45 s; on the live feed
  on 2026-11-06 it read 15 new 5.02 filings in 87 s (local qwen3:4b), about 20 SEC requests.
- Context per change (`app/services/leadership_context.py`): latest observations filed by the
  filing date; revenue growth and operating margin over the three fiscal years before, over the
  tenure when the appointment was recorded, and two-digit SIC peer medians.
- Base rates (`scripts/backtest_officer_changes.py`, docs/benchmarks/officer-changes-base-rates-2026-11.md):
  54,736 company-years, 8,762 companies, 232,488 item 5.02 filings. Filing any 5.02 in a year:
  48.9% beat peers' next-year revenue growth (95% CI 48.3-49.4) against 50.5% (49.8-51.1)
  without; four or more: 45.3% (44.2-46.3), median 1.2 pp below peers, while 53.2% beat peers'
  margin change. Presence alone carries little; no score or weight is built on it.
- Not done: GDELT corroboration (optional), and role-level base rates (CEO/CFO departures), which
  need many more filings read by the model than the 70 read so far.
