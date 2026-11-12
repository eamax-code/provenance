# Future scope

This file lists sources and sub-products the owner has flagged for later. Nothing here is planned
yet. Each entry needs a ticket, plus a check of the source's terms in
[data-rights.md](data-rights.md), before work starts.

## EIA-860: US power plants and generators

- **Link:** https://www.eia.gov/electricity/data/eia860/
- **What it is:** The US Energy Information Administration's annual survey of every electric
  generator of 1 MW or more at US power plants. For each plant it gives the location, operator and
  owners. For each generator it gives the capacity, technology, energy source, status, operating
  year and planned retirement. It also covers environmental equipment, storage and solar/wind
  detail. It is published as yearly Excel files back to 2001, with a monthly preliminary update
  (EIA-860M) that tracks plants being built, coming online and retiring.
- **Why it fits:** It adds physical assets behind company filings. A utility's or power producer's
  10-K figures could link to the plants and megawatts it owns, with plant openings and retirements
  added to the event feed. It could become a first sub-product for energy and infrastructure
  analysts, and it pairs with economic data (GH #28).
- **Open questions:**
  - Matching EIA utility and owner IDs to SEC filers (CIK) and LEIs.
  - How far back to load the history.
  - The terms: EIA data is a US government work and is generally public domain, but this must be
    confirmed and the credit line recorded.
