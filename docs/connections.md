# Connections graph: what it shows and what it can show next

The Explorer's **Connections** tab and `GET /v1/companies/{cik}/graph` (ADR 0011) draw a company
with the people and entities its filings name. Every edge links the filing it comes from.

## Built (November 2026)

| Layer | Source | What an edge says | Freshness |
|---|---|---|---|
| Insiders | Forms 3, 4, 5: SEC quarterly data sets, newer filings from their XML | officer (with title), director, 10% owner; since, last filed, shares held, open-market buys and sells over 12 months | data sets quarterly; per company on demand (7 days) |
| Board interlocks | the same data | this insider also files at company X, with the role there | as above |
| 5% holders | Schedules 13D and 13G, structured since Dec 2024 | stake %, shares, schedule, group members | on demand, three-year window |
| Subsidiaries | 10-K exhibit 21, 20-F exhibit 8 | name, jurisdiction, new since last year, gone since last year | on demand, latest two annual reports |

List endpoints return the same data: `/insiders`, `/insider-transactions`, `/holders`,
`/subsidiaries`. MCP tools: `company_connections`, `insider_transactions`.

Loaded locally on 18 November 2026: 20 quarters of insider data sets (2021 Q4 to 2026 Q3).

## What to add next, ranked

Value is for the buyers in `docs/launch-plan.md` (quant researchers, compliance and KYC teams,
fintech builders, agent builders). Effort: S under two days, M a week, L more.

| # | Addition | Source (licence) | Why it matters | Effort |
|---|---|---|---|---|
| 1 | **Leadership changes on insider edges**: appointed and departed dates from 8-K item 5.02, so a departure ends the edge at once instead of after two years without filings | `officer_changes` table, already extracted | makes "current board" exact; ties two products together | S |
| 2 | **Insider signals**: cluster buying (3+ insiders buying within 30 days), first purchase in years, sales under a 10b5-1 plan vs discretionary; event type `sec.insider_trade` and webhooks | loaded data | the most asked-for insider product; alerts are paid-plan material | S-M |
| 3 | **Person view**: `GET /v1/people/{owner_cik}`, every company a person reports on, roles over time, trades | loaded data | KYC and due diligence start from a person, not a company | S |
| 4 | **Institutional holders (13F)**: managers holding the company each quarter, with shares and value; CUSIP to CIK from the CUSIPs on 13D/G and the 13F's own issuer names | SEC Form 13F data sets (public) | "who owns this" is what Bloomberg and FactSet sell; closes GH #24 | M-L |
| 5 | **Co-registrants**: companies filing under the same accession (utility holding companies and their utilities, guarantor subsidiaries) | `filings` table plus an index on accession | registrant subsidiaries with their own filings, free | S |
| 6 | **Legal-entity parents and children** from GLEIF level 2 ("who owns whom") for companies with an LEI | GLEIF (CC0), client exists | official IDs for subsidiaries, foreign ultimate parents | S-M |
| 7 | **Deal counterparties**: mergers and tender offers from Forms 425, S-4, SC TO-T and DEFM14A ("subject company" and "filed by") | EDGAR filing headers | M&A edges with dates; event feed type | M |
| 8 | **Auditor and engagement partner** | 10-K cover XBRL (`dei:AuditorName`, firm ID) and PCAOB Form AP (public download) | shared-auditor graph; auditor changes are a known risk signal | M |
| 9 | **Fund holdings (N-PORT)**: mutual funds and ETFs holding the company | SEC N-PORT data sets (public) | completes ownership with GH #24 | L |
| 10 | **Related-party transactions and family relationships** from the proxy (DEF 14A) | model extraction with verbatim evidence, as for 8-K 5.02 | governance and AML use; needs the hosted model (GH #13) | M |
| 11 | **Underwriters and advisers** from final prospectuses (424B) | prospectus covers, already read for IPOs | bank to issuer edges | M |
| 12 | **Graph export** as CSV, GraphML and JSON for Neo4j and Gephi | the API | analysts work in their own tools; paid-plan export | S |
| 13 | **Shared addresses**: registrants at the same business address | submissions addresses, already stored | shell-company and AML screening | S |
| 14 | **Government contracts and lobbying** | USAspending.gov and Senate LDA (public domain) | outside EDGAR; see `docs/future-scope.md` | L |

## Limits to say out loud

- Form 4 has no end date for a role. Until item 1 lands, an insider is former after two years
  without a filing.
- Exhibit 21 lists significant subsidiaries only; companies may leave out the rest, and some
  list hundreds. The graph groups more than 24 by jurisdiction.
- 13D/G before December 2024 are free text and are not read, so a holder that has not filed
  since then is missing until its next amendment.
- Names of insiders are public in EDGAR. Their addresses are in the same filings and are never
  stored. A person view (item 3) should go through legal review (ticket 05) for EU and UK
  visitors.
