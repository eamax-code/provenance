# Mapping 1.5.0: changelog and quality-report drafts

Built and committed (2a38745, 23abf7a); the rules run only at `MAPPING_VERSION` 1.5.0, so the
live mapping stays 1.4.1 until the full pass. Counts below are from the dry run on the built code
against the local companyfacts archive (2026-11-22); the quality report replaces them with the
pass's own figures.

## Changelog entry (draft)

**Revenue, mapping 1.5.0 (2026-11-23).** Two changes to how revenue is read. Both restate figures
we published before; every changed value is listed in the data-quality report, and answers for an
earlier date (`as_of`) carry the mapping version that produced them.

1. *The income-statement line decides.* When a filing reports revenue under two tags that
   disagree, the one the filing shows on its income statement is now the figure, provided it is
   the only revenue line there and is labelled as a total ("Revenues", "Total revenues", "Net
   sales"). 638 published annual and quarterly values change at 91 companies, and 1,724 values
   that were marked ambiguous now have a figure. Examples: Republic Services 2022 is $13,511M as
   on its income statement (we showed $15,645M, a gross figure); Williams 2025 is $11.95B (we
   showed none). Filings before 2021 are unchanged.
2. *Bank revenue for banks that report in IFRS.* For banks and credit institutions, revenue is
   now the total income line on the income statement, after interest expense, as the bank labels
   it ("Total operating income", "Total income", "Total revenues"), where the filing shows that
   line. This adds 55 bank-years at 10 banks, among them HSBC ($68,274M total operating income,
   2025), UBS Group ($49,573M total revenues), Santander (EUR 58,670M total income) and BBVA
   (2020). This is net of interest expense, so it is not comparable with US banks' gross revenue
   figures.

## Quality report, before/after section (draft)

### Mapping 1.5.0: what changed (two rules, shown apart)

| Rule | Values changed | Newly ok | Lost ok | Companies |
|---|---|---|---|---|
| Income-statement line settles disagreeing tags | 638 | 1,724 | 0 | 730 (91 with a changed value) |
| IFRS bank total income | 0 | 216 (55 bank-years) | 0 | 10 |

Tag-only changes (the same value now cited under the income-statement tag): 8,308.

Hand-checks on the built code: 30 companies against each filing's rendered income statement,
30 right (Williams 2025 $11.95B; Republic Services 2022 $13,511M; Plexus net sales; Aspira,
bioAffinity and Autoscope total revenue; HSBC, Santander, Galicia and SEK total income). The
dry run before building: income-statement rule v3, 1 doubtful in 20; IFRS banks, 20 of 20.

Definition used: bank revenue = the total income line on the income statement, after interest
expense, as the bank labels it. Only where the filing's own income statement shows
ifrs-full RevenueAndOperatingIncome or GrossProfit under such a label; only for SIC 6000-6199.
