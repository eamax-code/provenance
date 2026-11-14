# Pilot launch plan

Written 2026-11-15. This is the plan for putting Provenance in front of strangers and learning,
within 30 days, whether they will pay. It sits alongside AGENTS.md §16 (go/no-go) and the
working list in TODO.md.

## The bet

AI products are starting to answer questions about companies, and most of them cannot show
where a number came from. A model that states revenue without a source is a liability for a
fintech, a research tool or an analyst. **Provenance is the citable source of public-company
facts:** every figure carries the filing it came from (accession number, XBRL tag, mapping
version), can be asked "as of" a past date, and reaches an agent through one MCP line.

The data is public, so the cost of goods is low. The value is in what is hard to do well:
normalising thousands of companies' XBRL into a few trustworthy metrics, refusing to guess,
keeping the history honest (no look-ahead), and delivering it where builders work (REST, Python,
the event feed, webhooks, MCP).

## Who it is for, in order

1. **AI application builders**: copilots, research agents and chat products that must cite
   figures. They feel the hallucination problem and adopt MCP quickly. The pitch: "Your agent
   can now state a company's revenue and link the 10-K that reports it."
2. **Small fintech and data teams**: screens, dashboards, alerting and backtests that need
   point-in-time fundamentals without a terminal licence. The pitch: `as_of` without look-ahead,
   an event feed, and signed webhooks.
3. **Analysts and researchers**: the Financial Chat and the Company Explorer, as the front door
   and the demo. They convert into (1) and (2) inside their companies.

Not for now: traders who need prices or intraday data. We say so plainly (no market data).

## What makes it different

| | Provenance |
| --- | --- |
| Trust | Every value links to its filing; `quality_status` and `derived` say when to be careful; missing means missing, never zero |
| Time | `as_of` on figures, the screen and search: what was known on a date, restatements hidden until filed |
| Agent-native | MCP server, `llms.txt`, an OpenAPI reference, and chat that cites |
| Coverage | 21,586 SEC filers loaded, plus new listings on 38 venues in the EU, the UK and Canada |
| Honest scope | No prices, estimates or vendor data, and every page says so |

## The pilot offer

- **Free:** 60 requests a minute, 10,000 a month, the MCP server and the Python client.
- **Builder ($49 a month) and Team ($199):** as on the pricing section. During the pilot,
  **the first ten design partners get Builder free for 60 days** in exchange for a 30-minute
  call every two weeks and permission to quote them. Each one is arranged by hand until billing
  (GH #16) exists.
- **Enterprise:** bulk access and terms only after the legal review (ticket 05).

## How we will know (first 30 days)

Business (AGENTS.md §16): 15 interviews, 5 hands-on trials with a real use case, 3 explicit
willingness-to-pay signals, 2 paid pilots (or 1 with a clear follow-on).

Product, read weekly with `python scripts/pilot_metrics.py` (from `api_usage`, `accounts` and the quality snapshots):

| Measure | Target |
| --- | --- |
| Sign-up to first successful call | under 10 minutes, median |
| Activation: an account's keys make 10 or more calls in their first day | 40% |
| Weekly active keys (any call in 7 days) | 25 by day 30 |
| MCP: keys whose calls arrive through `/mcp` | 30% of active keys |
| Facts with `quality_status=ok` | at least 95% (95.4% today) |
| Filing to API, watched companies | measured and published on the status page, no promise |

The decision rule stays as written in AGENTS.md: go if they pay for provenance plus freshness
plus convenience; iterate on coverage, depth or integrations if they like it but will not pay;
stop expanding if 15 interviews and 5 trials show no willingness to pay.

## Decisions that block launch (yours)

In the order they unblock things:

1. **Host and domain (02).** Fly or Render; the deploy files and the settings table in
   docs/deployment.md are ready. About ₹4,000 a month at pilot scale.
2. **Email provider (06).** Sign-in links depend on it. Until then, sign-in points visitors to
   the key request form.
3. **Where the model runs (GH #13).** Chat already answers figures, trends, rankings and tables
   from data without a model; the model adds written answers, summaries and forecasts. Options:
   a hosted API with a budget cap, or no model at launch.
4. **News for forecasts (GH #14).** Google News RSS is personal-use only; switch to GDELT, a
   licensed feed, or turn forecasts' news off for the pilot.
5. **Legal review and final name (05)** before paid plans; the draft legal pages are up at
   `/legal/` with bracketed notes for counsel.
6. **Billing (GH #16)** can wait until the first design partner wants to pay.

## Launch-day checklist

- [ ] Deploy, `GET /readyz` is `ready`, new secrets set (docs/security.md, "Before launch")
- [ ] `PUBLIC_BASE_URL` and `site/shell/site.json` set to the domain; `sync_site_shell.py` run
- [ ] SEC archives loaded (`scripts/sec_bulk.py`), marts built, poller running, listings job scheduled
- [ ] Email sends a sign-in link to a real inbox; webhook delivery to a real receiver verified
- [ ] `ALERT_WEBHOOK_URL` set; one alert tested
- [ ] Status page shows fresh data; footer figures are live
- [ ] Python client published (`client-v0.1.0` tag) and the MCP line tested from Claude Code
- [ ] Announcement posted; first ten design partners contacted

## Where to find the first users

- **Show HN:** "Provenance: SEC financials API where every number cites its filing (with an MCP
  server)". Link the Playground and the Developer docs, not the home page.
- **MCP directories and agent communities:** the official MCP registry and the community lists.
  The listing is the one-line install.
- **Python and data communities:** a notebook that backtests a screen with `as_of` and shows the
  look-ahead it avoids.
- **Direct:** 40 founders of AI research and fintech copilots, found through their own launch
  posts. Use the message below and offer the design-partner deal.

Outreach message (edit the first line for each person):

> Saw [their product] answers questions about public companies. Does it cite where each
> figure comes from? We built Provenance so it can: every value from SEC filings links to the
> exact 10-K or 10-Q, you can ask what was known on any past date, and agents connect in one
> line over MCP. Free to try at [domain]/developers/. We are taking ten design partners: Builder
> free for 60 days for a short call every two weeks. Interested?

## The next 90 days, if the pilot says go

Built in this order because each widens the questions an agent can answer with a citation:

1. Ownership: insider trades, 13F, 13D/G and fund holdings (GH #24).
2. About 100 standardised line items and segments (GH #25).
3. Company guidance quoted from earnings releases (GH #26).
4. Economic data (GH #28) and an Excel and Sheets add-in (GH #30).
5. A first sub-product from the future-scope list: US power plants from EIA-860, linked to the
   utilities that file with the SEC (docs/future-scope.md).

## Risks we are watching

| Risk | Mitigation |
| --- | --- |
| Larger API vendors add citations | Point-in-time, honest quality flags and agent-native delivery are habits, not features; move fast with design partners |
| Model cost or reliability | Data-first answers already work without a model; cap model use per key (done: 200 chat questions a day) |
| Data rights | SEC, ESMA, FCA and GLEIF terms recorded in docs/data-rights.md; Google News removed before paid plans; legal review before bulk deals |
| One-person operations | Alerts, a status page, a nightly archive load that resumes, and a test suite of 464 checks on SQLite and PostgreSQL |
