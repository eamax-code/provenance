# TODO

Pending work as of 2026-11-11. GitHub Issues (GH #) and older tickets in `.scratch/backlog/issues/`; tracker
conventions in `docs/agents/issue-tracker.md`. Labels: **ready-for-human** needs an owner
decision or account; **ready-for-agent** can be built now; **needs-triage** is an idea.

## Release 1.0
Checklist: [GH #31](https://github.com/eamax-code/provenance/issues/31). Milestone "Release 1.0" on GitHub.

### Needs you
| # | Item | Why it is blocked |
| --- | --- | --- |
| 02 | [Choose a host and deploy the pilot](.scratch/backlog/issues/02-deploy-pilot.md) | Account, domain, payment |
| 05 | [Legal review of data rights; final name](.scratch/backlog/issues/05-legal-and-brand.md) | Before selling |
| 06 | [Email provider](.scratch/backlog/issues/06-email-provider.md) | Account and sender domain; sign-up needs it |
| GH #13 | [Production language model: where chat, extraction and forecasts run](https://github.com/eamax-code/provenance/issues/13) | Hosted API or GPU host, and a budget |
| GH #14 | [Forecasts: replace Google News RSS before selling](https://github.com/eamax-code/provenance/issues/14) | GDELT, a licensed API, or filings only |
| GH #16 | [Billing for Builder and Team](https://github.com/eamax-code/provenance/issues/16) | Payment provider; prices |
| GH #17 | [Terms, privacy, acceptable use, data sources pages](https://github.com/eamax-code/provenance/issues/17) | Drafts can start; final after 05 |
| GH #23 | [Credits, levels and quests in chat and the playground](https://github.com/eamax-code/provenance/issues/23) | Reward amounts; needs #15 |
| 20 | [Officer changes: confirm the "evidence, not signals" framing (and Indian counsel on SEBI rules) before any score](.scratch/backlog/issues/20-officer-change-analysis.md) | Your decision; the feed, context and base rates are built |
| 03 | [Live-week pilot report and outreach](.scratch/backlog/issues/03-pilot-report-and-outreach.md) | Needs a deployment and interviews |

### Ready for agent
| # | Item |
| --- | --- |
| GH #11 | [One layout and the dark theme on every page](https://github.com/eamax-code/provenance/issues/11) (done, closed 2026-11-12) |
| GH #12 | [Theme choice in the profile for chat and the Explorer](https://github.com/eamax-code/provenance/issues/12) (done, closed 2026-11-12) |
| GH #10 | [Company page: a figure's mini trend opens a large chart with insights](https://github.com/eamax-code/provenance/issues/10) (done, closed 2026-11-12) |
| GH #15 | [Accounts: self-serve sign-up, sign-in and a profile](https://github.com/eamax-code/provenance/issues/15) (email delivery waits on 06) |
| GH #18 | [Security review before launch](https://github.com/eamax-code/provenance/issues/18) |
| GH #19 | [Production data and monitoring](https://github.com/eamax-code/provenance/issues/19) (after 02) |
| GH #20 | [Developer docs: quickstart, guides, changelog, versioning, PyPI](https://github.com/eamax-code/provenance/issues/20) |
| GH #21 | [Launch polish: SEO, accessibility, performance, 404](https://github.com/eamax-code/provenance/issues/21) |
| GH #22 | [MCP server so AI agents can query Provenance and cite it](https://github.com/eamax-code/provenance/issues/22) |

## After release
Milestone "After release": the gaps with Bloomberg and FactSet that free, redistributable sources can close.

| # | Item | Status |
| --- | --- | --- |
| GH #24 | [Ownership: insider trades, 13F, 13D/G, fund holdings](https://github.com/eamax-code/provenance/issues/24) | ready-for-agent |
| GH #25 | [About 100 standardised line items and segments](https://github.com/eamax-code/provenance/issues/25) | ready-for-agent |
| GH #26 | [Company guidance from earnings releases](https://github.com/eamax-code/provenance/issues/26) | ready-for-agent |
| GH #27 | [Company financials outside the US](https://github.com/eamax-code/provenance/issues/27) | needs you: licence per source |
| GH #28 | [Economic data: rates, inflation, output](https://github.com/eamax-code/provenance/issues/28) | ready-for-agent |
| GH #29 | [Market prices: licensed end-of-day or the user's key](https://github.com/eamax-code/provenance/issues/29) | needs you: vendor and budget |
| GH #30 | [Excel and Google Sheets add-in](https://github.com/eamax-code/provenance/issues/30) | ready-for-agent |
| 19 | [Bulk Parquet snapshots](.scratch/backlog/issues/19-parquet-snapshots.md) | needs you: bounded-export rule, 05 |
| 04 | [TMX / CSE permissions for Canadian feeds](.scratch/backlog/issues/04-canadian-exchange-permissions.md) | needs you: non-commercial terms |

## Future scope
Sources and sub-products flagged for later, each with a description: [docs/future-scope.md](docs/future-scope.md).
So far: EIA-860 (US power plants and generators).

## Done
GH #9 the company page is Snapshot, with Report and Dossier as layouts a reader picks (2026-11-10), 21 the ChatGPT design with clay.com-style motion is the main page (2026-11-06), 01 (SEC contact address in local config; 20,540 companies loaded from the bulk archives), 11 usage series, SEC responses by endpoint, detection-to-processing latency, 07-10 listings: GLEIF identity in batches, non-share exclusion and primary-listing flag,
listing watches, Listings view in the Explorer; 12 shared rate limits, 20 officer changes on the feed within minutes with point-in-time
context and measured base rates, daily retention, webhook alerts, 15 test hygiene
(no warnings, `--clock`), 16
point-in-time facts, 17 event feed, 18 Python client. GitHub Issues #1 to #8 are closed (search,
marts, profiles and /v1/search, chat flow, redesigns).

## Ideas
| # | Item |
| --- | --- |
| 13 | [Canadian reporting issuers from OSC open data](.scratch/backlog/issues/13-canada-reporting-issuers.md) |
| 14 | [Company event feed (information, not signals)](.scratch/backlog/issues/14-event-feed-idea.md) |

Outside this repo: the DistrictLens cyclone module spec is at
`apps/research/districtlens-cyclone-impact-spec.md`; it needs a repo location before tickets,
and GDACS (JRC) and JTWC reuse confirmations before a paid tier.
