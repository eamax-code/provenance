# TODO

Pending work as of 2026-11-06. One ticket per item in `.scratch/backlog/issues/`; tracker
conventions in `docs/agents/issue-tracker.md`. Labels: **ready-for-human** needs an owner
decision or account; **ready-for-agent** can be built now; **needs-triage** is an idea.

## Needs you
| # | Item | Why it is blocked |
| --- | --- | --- |
| 02 | [Choose a host and deploy the pilot](.scratch/backlog/issues/02-deploy-pilot.md) | Account, domain, payment |
| 03 | [Live-week pilot report and outreach](.scratch/backlog/issues/03-pilot-report-and-outreach.md) | Needs a deployment and interviews |
| 04 | [TMX / CSE permissions for Canadian feeds](.scratch/backlog/issues/04-canadian-exchange-permissions.md) | Non-commercial terms |
| 05 | [Legal review of data rights; final name](.scratch/backlog/issues/05-legal-and-brand.md) | Before selling bulk access |
| 06 | [Email provider](.scratch/backlog/issues/06-email-provider.md) | Account and sender domain |
| 20 | [Officer changes: confirm the "evidence, not signals" framing (and Indian counsel on SEBI rules) before any score](.scratch/backlog/issues/20-officer-change-analysis.md) | Your decision; the feed, context and base rates are built |
| GH #11 | [One layout for every page (the home page's header, menu, footer, tokens)](https://github.com/eamax-code/provenance/issues/11) | Waits on your theme choice |
| 19 | [Bulk Parquet snapshots](.scratch/backlog/issues/19-parquet-snapshots.md) | Changes the bounded-export rule; legal review (05) |

## Ready for agent
| # | Item |
| --- | --- |
| GH #10 | [Company page: a figure's mini trend opens a large chart with insights](https://github.com/eamax-code/provenance/issues/10) (built 2026-11-10; waiting on your review) |

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
