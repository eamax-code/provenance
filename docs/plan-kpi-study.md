# Q-08 KPI study: company extension tags in the top 100 (study only)

Status: **study** (2026-11-25), for the PM. Nothing is loaded or shown.

## Question

Do the largest companies tag their operating KPIs (members, subscribers, stores, aircraft and
the like) as XBRL extension tags we could read and show as filed, beside the standard figures?

## Method

- **Source:** the SEC's Financial Statement and Notes data sets, already in `SEC_BULK_DIR/fsn`, for
  the last 12 monthly files (November 2025 to October 2026). Unlike the company facts API, which
  holds standard taxonomies only, these keep a company's own extension tags (`num.tsv` rows whose
  version is the filing's own accession).
- **Companies:** the top 100 by latest annual revenue among USD reporters in our marts, and their
  10-K and 10-Q filings in the window: 333 10-Qs, 84 10-Ks and 2 10-K/As.
- **A KPI candidate:** an extension tag with a value that is not in USD, not a percentage of a
  member, and carries no dimensions (one figure for the company). Units such as pure (ratios),
  shares, employee, aircraft, store.

## Findings

- **79 of the 100 use extension tags** in the window, with a median of 67 a company. The 21 with
  none are mostly 20-F and 40-F filers outside this form set (Shell, BP, TotalEnergies, HSBC,
  Petrobras, Equinor, ArcelorMittal) and old registrants whose latest revenue in our marts is
  years old (Google Inc., Medco, Aetna, Walgreen Co., Dow Chemical, FCA US).
- **683 KPI candidates at 72 companies,** grouped by name:

| Kind | Candidates | Examples |
|---|---|---|
| Other | 215 | mixed one-off counts and ratios |
| Equity and plans | 155 | votes per share, plan purchase periods, pension asset caps |
| Tax rate | 140 | lines of the effective tax rate reconciliation |
| Debt and rates | 68 | weighted average interest rates of scheduled repayments |
| Operating | 68 (at 34 companies) | FedEx aircraft purchase obligations (56) and idle aircraft (22); Sysco distribution facilities (337); Kroger stores closed (60); Valero refining throughput (3.2m bbl/day) and ethanol capacity (1.7bn gal/year); Caterpillar countries served by dealers (190); CVS pharmacy plan members (88m) and patients served (800,000) |
| Legal | 37 | complaints, cases, claims and investigations |

- **Operating KPIs are thin and mostly one-off.** Most operating candidates are counts tied to an
  event or a note (aircraft due by year, stores closed, projects with capitalised well costs),
  not the recurring headline KPIs analysts follow (paid members, daily users, subscribers, trips).
  Those are usually in the earnings release and MD&A text, or tagged with dimensions, which this
  pass did not count.

## Recommendation

1. **Don't build a KPI feature on undimensioned extension tags.** They would give a few dozen
   companies a scattering of one-off counts, labelled by each company's own tag name.
2. **If KPIs stay a goal,** do a second study on 15 named companies with known headline KPIs
   (Netflix, Meta, Uber, Airbnb, Costco, Walmart, Delta, Marriott, Starbucks, T-Mobile, Verizon,
   AT&T, UnitedHealth, Tesla, Amazon). Read their dimensioned extension facts and the earnings
   release exhibits we already store (`filing_sections`, 13,364 `ex:99.1` releases). Count how many
   headline KPIs each source carries per quarter, with the exact figure checked against the
   document.
3. **Top-100 selection:** future studies should use active filers only (a 10-K or 20-F in the
   last two years) so stale registrants do not take places.

## Reproducing

The script is in this session's scratch folder (not committed): it reads `sub.tsv`, `tag.tsv` and
`num.tsv` from the last 12 `fsn/*_notes.zip` files. About 70 seconds, no SEC requests, no
database writes.
