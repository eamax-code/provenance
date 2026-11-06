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
| 19 | [Bulk Parquet snapshots](.scratch/backlog/issues/19-parquet-snapshots.md) | Changes the bounded-export rule; legal review (05) |

## Ready for agent
| # | Item |
| --- | --- |
| 07 | [Issuer identity for every listing from GLEIF bulk files](.scratch/backlog/issues/07-listings-issuer-identity-at-scale.md) |
| 08 | [Listings data quality: structured products, primary-listing flag](.scratch/backlog/issues/08-listings-data-quality.md) |
| 09 | [Watches and webhooks for listing events](.scratch/backlog/issues/09-listing-watches.md) |
| 10 | [Listings in the Explorer app](.scratch/backlog/issues/10-explorer-listings.md) |
| 11 | [Close partial review items: usage series, SEC metrics, latency](.scratch/backlog/issues/11-console-and-metrics-gaps.md) |
| 12 | [Multi-replica rate limits, retention schedule, alerts](.scratch/backlog/issues/12-multi-replica-and-ops.md) |
| 15 | [Test-suite hygiene](.scratch/backlog/issues/15-test-suite-hygiene.md) |
| 20 | [Officer changes: the remaining parts (event feed, tenure context, backtests)](.scratch/backlog/issues/20-officer-change-analysis.md) |

## Done
21 the ChatGPT design with clay.com-style motion is the main page (2026-11-06), 01 (SEC contact address in local config; 20,540 companies loaded from the bulk archives), 16
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
