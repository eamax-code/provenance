# 20: Officer-change analysis from 8-K Item 5.02 (evidence, not signals)

**What to build:** When a company files an 8-K with Item 5.02 (an officer or director departs or is appointed), extract who, which role, appointed or departed, the effective date, any stated reason or "disagreement", and the interim or successor. Each field quotes the filing text it came from. Add context computed from point-in-time facts: revenue and margin growth during the officer's tenure compared with the years before and with SIC peers. Publish it on the event feed within minutes of the SEC accepting the filing. An LLM only extracts and explains; every number comes from stored facts and every claim links to a filing.

**Blocked by:** 01 (live EDGAR polling needs the SEC contact address); owner decisions below.

**Status:** needs-triage

Research (2026-11-03): no free news API allows commercial use (NewsAPI, GNews, Finnhub, Alpha Vantage, Marketaux, Polygon/Massive and Tiingo free tiers are personal or non-commercial). PR Newswire and Business Wire forbid redistribution and data mining. Google News and Yahoo forbid automated commercial use. GDELT allows commercial use but gives headlines, URLs and tone only, with no article text. SEC EDGAR is free and redistributable; an 8-K appeared in the latest-filings feed about 2 minutes after acceptance. Item 5.02 must be filed within four business days.

- [ ] Owner: confirm framing as evidence-backed event records, not buy/sell signals (US publisher exclusion; get Indian counsel's view on SEBI research-analyst and investment-adviser rules)
- [ ] Owner: LLM provider and monthly budget
- [ ] Store 8-K `items` on filings; `items=` filter on `/v1/events`
- [ ] Poll EDGAR latest-filings (8-K) every 30-60 s within fair-access limits
- [ ] Extraction with verbatim evidence spans (each span checked against the filing text); low-confidence results marked
- [ ] Tenure context from point-in-time facts; peer comparison by SIC
- [ ] Before any score or weighting: backtest historical 5.02 events with `as_of` to measure base rates, and publish base rates instead of hand-set weights
- [ ] Optional: GDELT headline links as corroboration (metadata only, with attribution)
