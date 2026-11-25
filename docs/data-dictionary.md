# Data dictionary

All timestamps are UTC (`TIMESTAMPTZ`), serialized as ISO 8601 with a `Z` suffix. Dates are
`YYYY-MM-DD`. Missing values are `null`, never `0`.

These tables describe the stored columns. Some stay internal and are never returned by the API,
the site or the chat: `first_detected_at` and `source_updated_at` on every table, `source_url`
on `companies` (a source API address), and `source_url` on the listing tables (register files
and feeds). Responses link only to documents and filings: a filing's EDGAR index page, and a
company's EDGAR filing list as `filings_url`.

## Quality statuses (controlled vocabulary)

| Status | Meaning |
| --- | --- |
| `ok` | Required fields present and mapping unambiguous |
| `partial` | One or more optional fields/timestamps unavailable in the SEC source |
| `ambiguous_mapping` | Several candidate XBRL tags cover the period, or they disagree, or the source period type did not match the metric. M-01: also a figure one filing reports beside another for the same metric and period under the other taxonomy (an IFRS filer whose parent-only schedule is tagged in US GAAP: Banco Santander Chile's 2019 liabilities, CLP 47.1 trillion consolidated and 8.39 trillion parent-only, in one 20-F) that the company's other filings for the period do not back (within half a percent). When neither is backed, both are, and the statement cell is blank with a `quality_note`, unless another filing's figure for the period is shown. Majority, never magnitude. Set by `scripts/flag_filing_conflicts.py` and after each company ingest (`app/services/filing_conflicts.py`) |
| `unit_doubtful` | S-06: an EPS that, as filed, is within 5% of 100 times the same filing's net income over weighted shares (probably cents or pence tagged as the main unit: Rio Tinto 2016-19, Pearson, Vodafone). S-06b: where the three are about 1,000 or 1/100 apart, the one figure (EPS, net income or weighted shares) the company's other filings for the same period show to be off: no other filing agrees with it, all differ by a round scale, and their figure alone makes the EPS reconcile (Waters' 59.5 billion weighted shares, Barrett's EPS 1,570, Palatin's net income in thousands); nothing when no single substitution, or more than one, reconciles. Value kept as filed, never rescaled; left out of every derived use (payout, ratios, screens, marts, chat) like any status other than `ok`/`partial`; statement cells carry `quality_note` (S-06: on the EPS and the shares cell it was checked against; S-06b: on the figure off, in its direction, citing a filing it was compared with); statements show another filing's agreeing figure for the period where one exists. Set by `scripts/flag_eps_reconcile.py` and after each company ingest; a re-ingest keeps it. Ratios near 1,000 or 1/100 are not flagged: there the share count or net income is usually the figure off |
| `invalid_source_value` | The SEC value could not be parsed as a number; `value` is `null` |
| `suspicious_period` | The period cannot be right: it ends before EDGAR began (1993) or more than two years after the filing that reported it (a typo in a date context, a founding year). Stored from mapping 1.4.1; never the latest figure |
| `stale` | Last successful SEC fetch is older than `FRESHNESS_STALE_AFTER_SECONDS` (freshness endpoint only) |
| `unavailable` | Source endpoint or requested fact not available |
| `derived` | Value computed by this service from two reported observations (`derived=true`, `derivation` present) |

## companies

| Column | Meaning |
| --- | --- |
| `cik` | 10-digit zero-padded SEC Central Index Key. Canonical identifier. |
| `legal_name` | Name from SEC submissions (or the ticker file before first ingestion) |
| `ticker`, `exchange` | Current primary ticker/exchange as listed by the SEC. Not a permanent identity. |
| `sic_code`, `sic_description`, `entity_type`, `state_of_incorporation`, `fiscal_year_end` | As reported in SEC submissions |
| `fiscal_year_offset` | S-05 (derived): years added to the end-year fiscal label, as the company's latest annual report names the year it reports ("fiscal 2025 ended January 31, 2026": -1, as Gap, Target and Home Depot; 0 where the wording confirms the end-year name). Set by `scripts/set_fiscal_year_offsets.py` for companies whose filings' DEI fiscal year proposes a different name; the DEI alone never sets it (Mentor Graphics tags 2016 for the year its 10-K calls fiscal 2017). Applies to every year (the report names its prior years the same way). Null: no such wording read, labels follow the end-year rule. Responses say which in `label_basis` |
| `fiscal_year_ends` | S-07 (derived): the company's own fiscal year ends, ISO dates oldest first: the year each annual report covers (its annual period ending at the filing's period of report, else its latest) and that report's comparative years ending on the same month and day (Eros' 2020 transition report brings STX's September years, the accounting acquirer's). A fiscal year is named by its own end date and a quarter by the own year end containing it, so a stale `fiscal_year_end` (Greif's September for its October years) no longer names years a year ahead. Annual statement columns are the periods ending, within a week, on the month and day of the nearest own year end (two sharing a label get the month: "FY2019 (Mar)", "FY2019 (Sep)"); other 12-month periods in a report (AAR's) stay in `/facts` but are not columns. A transition period (`app/services/fiscal_years.py`) is an annual report's latest period when no fiscal year ends on that date, it runs 2 to 11 months, starts the day after an own year ended and ends on the day of the next own year end (with no later year, only a 10-KT): a 10-KT, or a 20-F or 10-K transition report; it is its own column, "Transition period (N months, ended date)", never a fiscal year. A report's run of years back from its own year brings older years and a transition between two of them (Cenntro's June years and 7-month transition), but only one short period between years ending on different days: a predecessor's and successor's parts of one year (Frontier's emergence, Waldencast's merger, 44 such) are never a transition. Quarters of a transition run in sequence from its first day and are "Transition Qn (ended date)"; a later report's recast calendar quarter inside it (Pandora's) keeps its own label. Not a transition: a later interim in a 10-K (SafeSpace), a new company's first short period. S-07b: one annual column per fiscal year end. Among period ends within a week of one year end, the column is the end with the most figures in that statement, then an annual report's period of report, then the nearest; the others stay in `/facts`: adoption-date balances beside the year end (LATAM's January 1, 2 and 4, 2018; Group 1 Automotive's ASC 606 January 1, 2018), a stray figure dated a day off a 52/53-week year end (Onto's). Where a restated opening balance is the full balance sheet and the year end carries only a cash figure (Avino's January 1, 2016), the opening balance is the column, dated as filed. 1,615 balance, 189 income and 162 cash-flow columns at 1,348 companies no longer show. Known limit: a transition period ending on the same date as a fiscal year shows as the fiscal year in the statements (Eros' STX six months to March 2020 and its own FY2020); both are in `/facts`. A short year after a change whose cover ticks "annual" (Wayne Savings, Red Giant) is labelled a transition period; `transition_form` gives the cover's form. Set by `scripts/set_fiscal_year_ends.py` |
| (S-05 known filer DEI slips) | 23 companies whose 10-K wording confirms -1 but whose DEI fiscal year names some years otherwise; the offset applies to those years too (their own reports name them by the start year, e.g. Lands' End's FY2021 10-K: "Fiscal 2021 – The 52 weeks ended January 28, 2022"). Years given as the calendar year the fiscal year ends in: American Eagle Outfitters (2019); Albertsons (2021, 2022); Brand House Collective (2023, 2025); Build-A-Bear Workshop (2016, 2020, 2026); Bath & Body Works (2020); Children's Place (2024); Core & Main (2025, 2026); DAVIDsTEA (2021, 2022); DIH Holding US (2025); Dave & Buster's (2025); Five Below (2018); Foot Locker (2020); Hancock Fabrics (2015); J.Jill (2024); Lands' End (2022); NTT DOCOMO (2014-2017); Perfumania (2016, 2017); RH (2023, 2024); Shoe Station Group (2017, 2020, 2021); Sportsman's Warehouse (2025); Ulta Beauty (2015); Williams-Sonoma (2019); Zumiez (2026) |
| `source_url` | SEC submissions URL (or ticker file URL before ingestion) |
| `source_updated_at` | `Last-Modified` header of the submissions response, when the SEC sends one |
| `first_detected_at` | First time this service saw the company |
| `last_processed_at` | Last completed ingestion |
| `last_successful_fetch_at` | Last successful SEC fetch (drives `stale`) |
| `last_fetch_error_at`, `last_fetch_error` | Most recent failed attempt (redacted message). Data shown is from the last success. |
| `quality_status` | `ok` when filings and facts both ingested; `partial` otherwise |

SEC metadata from the submissions (issue #9), refreshed on each ingestion and backfilled from the
bulk archive by `scripts/load_aliases.py`: `filer_category` (e.g. "Large accelerated filer";
several statuses joined with "; "), `sec_office` (the SEC review office, `ownerOrg`), `ein`,
`lei` (rarely filed), `phone`, `website` and `investor_website` (rarely filed),
`business_address` and `mailing_address` (JSON: street1, street2, city, stateOrCountry, zipCode,
country), `tickers` and `exchanges` (JSON lists, every one the SEC lists), and
`insider_filings_as_issuer` / `_as_owner` (insiders file Forms 3, 4 and 5 about the company, or
the company files them about others). Empty strings are stored as null.

## filings

| Column | Meaning |
| --- | --- |
| `accession_number` | SEC accession number `##########-##-######`; unique per CIK |
| `form_type` | SEC form (`10-K`, `10-Q`, `8-K`, ...). `UNKNOWN` if missing in source. |
| `filing_date` | Date-only filing date from SEC |
| `report_date` | Period of report, when given |
| `accepted_at` | SEC `acceptanceDateTime` when present. Never inferred from `filing_date`. |
| `source_published_at` | Always `null`: the SEC submissions feed has no public-dissemination timestamp. Kept for schema stability. |
| `primary_document` | Primary document file name |
| `source_url` | `https://www.sec.gov/Archives/edgar/data/{cik}/{accession-no-dashes}/{accession}-index.html` |
| `source_payload_hash` | SHA-256 of the normalized source fields; unchanged payload = no update |
| `first_detected_at` | When this service first saw the accession number (preserved across re-ingestion) |
| `processed_at` | Last time the row was written |
| `ingestion_run_id` | Run that last touched the row |
| `quality_status` | `ok` or `partial` (e.g. acceptance timestamp missing) |

## financial_facts

One row per **source observation**: metric x tag x unit x period x accession. Restated values
from later filings are additional rows, never overwrites.

| Column | Meaning |
| --- | --- |
| `metric` | one of the thirty metrics in the concept mapping below |
| `value` | Numeric as reported (sign preserved). `null` if unparseable. |
| `unit` | XBRL unit (`USD`, `shares`, ...) |
| `currency` | ISO code when the unit is a currency or a currency per share; otherwise `null` |
| `period_start`, `period_end` | Duration bounds; `period_start` is `null` for instants |
| `period_type` | `duration` or `instant` |
| `period_class` | `annual` (350-380 days, from an annual report or another non-quarterly form), `ttm` (350-380 days in a 10-Q: trailing twelve months to a quarter end, since mapping 1.2.0), `quarterly` (80-100 days), `ytd` (160-290 days), `other`. For instants: by form (`10-K`=annual, `10-Q`=quarterly). Derived from the reported dates, **not** from the SEC `fp` label. |
| `fiscal_year`, `fiscal_period` | SEC `fy`/`fp` of the *filing* that reported the value (a 6-month YTD value carries `fp=Q2`; a 10-K's comparative for last year carries this year's `fy`) |
| `period_fiscal_year`, `period_label` | The fiscal year the period itself belongs to, and "FY2025" or "Q1 FY2026", from `period_end` and the company's fiscal year end (`app/services/periods.py`); `period_label` is null for ytd and other periods |
| `form_type`, `filed_date`, `accession_number` | Filing that reported the observation |
| `source_tag`, `source_taxonomy` | XBRL concept and taxonomy (`us-gaap`) |
| `source_url` | Filing index URL of the reporting filing |
| `mapping_version` | Version of the concept mapping (`1.4.1`; 1.4.1 rows replace 1.4.0 rows as each company is re-read) |
| `quality_status` | See table above |
| `derived`, `derivation` | Derived quarter values are only produced at query time (`include_derived=true`) and are not stored |
| `observation_key` | SHA-256 over metric, taxonomy, tag, unit, period, accession, derived flag; unique |
| `first_detected_at`, `processed_at` | Provenance timestamps |

### Concept mapping 1.4.1 (thirty metrics and two cover-page facts)

Generated from `CONCEPT_MAP` in `app/services/fact_normalizer.py`. 1.0.0 to 1.2.0 had the first
five metrics; 1.3.0 (2026-11-22, launch plan D-01) added the rest, industry fallback tags, the
unit check, cover-page facts and IFRS; 1.4.0 (2026-11-22): total-first revenue, in-filing
precedence, contract revenue as a component; 1.4.1 (2026-11-22): the notes below.

**1.4.1 notes.**
- Periods that cannot be right (ending before 1993, or more than two years after their filing)
  are stored as `suspicious_period` instead of being caught only when a figure is returned.
- Zero beside a nonzero candidate: in a total-first metric (revenue), a candidate valued 0 when
  another candidate in the same filing and period is nonzero is set aside as
  `ambiguous_mapping` ("zero beside a nonzero candidate tag"), not a conflict. Flowserve tags
  `Revenues` 0 beside $4.73B of contract revenue in its 10-K. A filing whose only figure is 0 (a
  company before revenue) keeps it as reported.
- `RegulatedOperatingRevenue` is a revenue fallback after
  `RegulatedAndUnregulatedOperatingRevenue`, used only for a period no candidate covers (ONE
  Gas has tagged nothing else since 2023).
- Not in 1.4.1, and why: banks reporting in IFRS (21, such as HSBC, Santander, UBS) tag their
  total operating income only in company-specific extension tags, which companyfacts leaves
  out; ifrs-full has no standard total, and adding net interest and net fee income would leave
  out trading and other income, so revenue stays absent for them. Williams' `Revenues` and
  contract revenue disagree in the same 10-K (eliminations); which line is on the income
  statement decides it, measured for a later mapping.

| Metric | Statement | Candidate tags, in precedence order | Industry fallbacks | Unit | Period |
| --- | --- | --- | --- | --- | --- |
| `revenue` | Income statement | `Revenues`, `RevenueFromContractWithCustomerExcludingAssessedTax`, `SalesRevenueNet`, `RevenueFromContractWithCustomerIncludingAssessedTax` | `RevenuesNetOfInterestExpense`, `RegulatedAndUnregulatedOperatingRevenue`, `RegulatedOperatingRevenue` | USD (as reported) | duration |
| `cost_of_revenue` | Income statement | `CostOfRevenue`, `CostOfGoodsAndServicesSold` | `CostOfGoodsSold` | USD (as reported) | duration |
| `gross_profit` | Income statement | `GrossProfit` | none | USD (as reported) | duration |
| `r_and_d` | Income statement | `ResearchAndDevelopmentExpense` | `ResearchAndDevelopmentExpenseExcludingAcquiredInProcessCost` | USD (as reported) | duration |
| `sga` | Income statement | `SellingGeneralAndAdministrativeExpense` | none | USD (as reported) | duration |
| `operating_income` | Income statement | `OperatingIncomeLoss` | none | USD (as reported) | duration |
| `interest_expense` | Income statement | `InterestExpense`, `InterestExpenseNonoperating` | `InterestExpenseOperating`, `InterestExpenseDebt` | USD (as reported) | duration |
| `net_interest_income` | Income statement | `InterestIncomeExpenseNet` | none | USD (as reported) | duration |
| `pretax_income` | Income statement | `IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest` | `IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments` | USD (as reported) | duration |
| `income_tax` | Income statement | `IncomeTaxExpenseBenefit` | none | USD (as reported) | duration |
| `net_income` | Income statement | `NetIncomeLoss` | none | USD (as reported) | duration |
| `eps_basic` | Income statement | `EarningsPerShareBasic` | `EarningsPerShareBasicAndDiluted` | USD/shares | duration |
| `eps_diluted` | Income statement | `EarningsPerShareDiluted` | `EarningsPerShareBasicAndDiluted` | USD/shares | duration |
| `shares_basic_weighted` | Income statement | `WeightedAverageNumberOfSharesOutstandingBasic` | `WeightedAverageNumberOfShareOutstandingBasicAndDiluted` | shares | duration |
| `shares_diluted_weighted` | Income statement | `WeightedAverageNumberOfDilutedSharesOutstanding` | `WeightedAverageNumberOfShareOutstandingBasicAndDiluted` | shares | duration |
| `d_and_a` | Income statement | `DepreciationDepletionAndAmortization` | `DepreciationAndAmortization` | USD (as reported) | duration |
| `cash_and_equivalents` | Balance sheet | `CashAndCashEquivalentsAtCarryingValue` | none | USD (as reported) | instant |
| `current_assets` | Balance sheet | `AssetsCurrent` | none | USD (as reported) | instant |
| `total_assets` | Balance sheet | `Assets` | none | USD (as reported) | instant |
| `current_liabilities` | Balance sheet | `LiabilitiesCurrent` | none | USD (as reported) | instant |
| `total_liabilities` | Balance sheet | `Liabilities` | none | USD (as reported) | instant |
| `long_term_debt` | Balance sheet | `LongTermDebtNoncurrent` | `LongTermDebtAndCapitalLeaseObligations` | USD (as reported) | instant |
| `long_term_debt_current` | Balance sheet | `LongTermDebtCurrent` | none | USD (as reported) | instant |
| `stockholders_equity` | Balance sheet | `StockholdersEquity` | none | USD (as reported) | instant |
| `retained_earnings` | Balance sheet | `RetainedEarningsAccumulatedDeficit` | none | USD (as reported) | instant |
| `operating_cash_flow` | Cash flow | `NetCashProvidedByUsedInOperatingActivities` | none | USD (as reported) | duration |
| `capex` | Cash flow | `PaymentsToAcquirePropertyPlantAndEquipment` | `PaymentsToAcquireProductiveAssets` | USD (as reported) | duration |
| `dividends_paid` | Cash flow | `PaymentsOfDividends` | `PaymentsOfDividendsCommonStock` | USD (as reported) | duration |
| `share_repurchases` | Cash flow | `PaymentsForRepurchaseOfCommonStock` | none | USD (as reported) | duration |
| `sbc` | Cash flow | `ShareBasedCompensation` | `AllocatedShareBasedCompensationExpense` | USD (as reported) | duration |
| `shares_outstanding` | Cover page (dei) | `EntityCommonStockSharesOutstanding` | none | shares | instant |
| `public_float` | Cover page (dei) | `EntityPublicFloat` | none | USD (as reported) | instant |

Not substituted, on purpose: net income attributable to the parent or to common shareholders,
cash including restricted cash, general and administrative alone for SG&A, short-term borrowings
for long-term debt due within a year. A company that does not report a concept has no value for
it: utilities often report no total liabilities, banks no gross profit or cash and equivalents.

**Banks:** revenue is `Revenues` when the bank reports it (JPMorgan does), otherwise
`RevenuesNetOfInterestExpense` (total net revenue); `net_interest_income` is
`InterestIncomeExpenseNet`; interest expense since the 2024 taxonomy is
`InterestExpenseOperating`. **Utilities:** revenue falls back to
`RegulatedAndUnregulatedOperatingRevenue`, then `RegulatedOperatingRevenue` (1.4.1), only for
years no candidate tag covers.

**IFRS (D-04):** foreign private issuers that file 20-F in IFRS (TSMC, SAP, Novartis; about 920
filers) are read from the `ifrs-full` taxonomy with `IFRS_MAP` in the same module: revenue is
`Revenue` or `RevenueFromContractsWithCustomers` (fallback `RevenueFromSaleOfGoods`), net income
is `ProfitLossAttributableToOwnersOfParent`, equity `EquityAttributableToOwnersOfParent`,
operating income `ProfitLossFromOperatingActivities`, interest expense falls back to
`FinanceCosts`. Currency is kept as reported (TWD, EUR, ...), never converted; many IFRS filers
also report a USD convenience translation for the latest year, stored as its own unit. The
company page's statements use the unit with the most fiscal years. Some 20-F filers (ASML) file
in US GAAP and are read as such.

**Precedence and conflicts are judged within one filing.** A filing's figure is the alternate
only when the same filing also reports a higher-precedence tag for the period, so a company that
moved tags (Revenues before 2018, contract revenue after) keeps every filing's figure.
**Revenue is total-first:** `Revenues` comes before contract revenue, and a smaller contract
revenue figure in the same filing is a component of the total, not a conflict (Berkshire
Hathaway: $371.4B total, $247.2B from contracts; insurance premiums are not contract revenue).
A larger alternate still flags the pair, except revenue including assessed taxes. This took
in-filing revenue conflicts from 57,872 periods at 2,075 companies to 6,359 at 630.

**Fallbacks** are used only for a (unit, period) no candidate tag covers. Where a candidate
covers it, the fallback observation is stored as `ambiguous_mapping` with the note "industry
fallback tag", and it is never compared with the candidates for conflicts.

**Derived figures (D-03)**, computed at query time from two reported figures and never stored
(`app/services/ratios.py`): `gross_margin`, `operating_margin`, `net_margin`,
`return_on_assets`, `return_on_equity` (percent); `debt_to_equity`, `current_ratio` (multiple);
`free_cash_flow` (operating cash flow minus capital expenditure, in the inputs' currency);
`book_value_per_share` (equity over the cover page's shares outstanding in the same annual
report). Inputs are paired by period class and period end (per share: by filing); figures in two
currencies are never combined; a divisor that is not positive gives no value. Every row has
`derived=true`, `quality_status=derived` and `derivation.inputs` with both filings. Accepted by
`/facts?metric=`, `/v1/facts/screen` and MCP.

**Unit check:** each metric has one unit kind (currency, per share, shares). An observation in
another kind (EPS tagged in `USD`) is `ambiguous_mapping`. `currency` is also set for per-share
units (`USD/shares` gives `USD`). The screen's default `unit` is the metric's own.

Precedence rule: for each (unit, period), the first tag in the list that has observations is
*preferred*. Preferred observations are `ok`; alternates are `ambiguous_mapping`. If the
latest-filed values of two tags disagree, the preferred one is also `ambiguous_mapping`.

API default view: one row per (metric, unit, period), the latest-filed `ok`/`partial`
observation. `revision_count` is the number of stored observations of that tag for the period;
`include_all_observations=true` returns them all.

## filing_sections

Text read once from a filing and kept, so it can be searched and re-read without the SEC.

| Column | Meaning |
| --- | --- |
| `cik`, `accession_number` | The filing the text came from (join `filings` for form and date) |
| `item` | `pr:*` prospectus sections (`pr:risk`, `pr:use`, …), `5.02` officer changes, `ex:99.1` earnings release |
| `status` | `ok`, `no_section`, `fetch_failed`; only `ok` rows are searched |
| `text` | Plain text, up to 250,000 characters per section |
| `source_url` | The filing's index page on sec.gov |
| `search_vector` | PostgreSQL only: a stored `tsvector` (English) generated from `text`, with a GIN index, used by full-text section search. Not in the ORM model. |

`section_chunks` (PostgreSQL with pgvector only): each searchable section cut into chunks of
about 1,500 characters with 200 of overlap, with `chunk_no`, the chunk `text`, a generated
`search_vector` and one `halfvec` embedding column per model (`embedding_bge` for bge-m3, the
default; `embedding_nomic` for nomic-embed-text), each with an HNSW index. Rows cascade with
their section.

`companies` also has PostgreSQL-only indexes for lookup: a trigram index on `lower(legal_name)`
(typo-tolerant names, `match_type: name_fuzzy`) and one on `upper(ticker)`.

## officer_changes

One change of a director or officer read from an 8-K item 5.02: `person`, `role`, `change_type`,
`what`, `effective`, `reason`, `successor`, `evidence` (the filing sentence), `verified` (the
person and the quoted words were found in the filing text), `source_url` (the 8-K on sec.gov),
`extractor_version`, `model`. `stream_status` and `stream_at` put changes read from 2026-11-06
on the event feed (earlier readings never stream). `context` (JSON): from the latest observations
filed by the filing date, revenue growth per year and operating margin over the three fiscal
years before the change (`before_change`, with the filings it used), the same over the person's
tenure when their appointment was recorded (`tenure`), and two-digit SIC peer medians (`peers`,
five or more companies).

## Connections graph (ADR 0011)

### insider_filings

One reporting owner on one Form 3, 4 or 5: `accession_number`, `issuer_cik`, `owner_cik`,
`owner_name` (as filed, usually last name first), `is_director`, `is_officer`,
`is_ten_percent_owner`, `is_other`, `officer_title`, `other_text`, `form_type`, `filing_date`,
`period_of_report`, `plan_10b5_1` (the filer ticked the Rule 10b5-1 box), `source`
(`dataset:2025q3` for the SEC's quarterly data set, `filing` when read from the filing's XML).
No addresses.

### insider_transactions

Table I (non-derivative) and table II (derivative) rows of a filing: `row_kind` (transaction or
holding), `security_title`, `trans_date`, `trans_code` (P purchase, S sale, A award, M exercise,
F tax withholding, G gift...), `shares`, `price`, `acquired_disposed` (A or D), `shares_after`,
`direct_indirect` (D or I), `nature_of_ownership`, `underlying_title`, `underlying_shares`,
`exercise_price`. Rows belong to the filing; a joint filing's rows count for each owner.

### insider_datasets

One loaded quarter: `quarter`, `sha256` of the zip, `filings`, `rows`, `last_filing_date` (the
newest filing it covers; later Forms are read one by one).

### subsidiaries

One line of an exhibit 21 (exhibit 8 of a 20-F): `cik`, `accession_number`, `form_type`,
`filing_date`, `exhibit` (e.g. EX-21.1), `position`, `name`, `jurisdiction` (as written),
`source_url` (the exhibit document). The latest two lists per company are kept.

### beneficial_owners

One reporting person on a structured Schedule 13D or 13G: `subject_cik`, `accession_number`,
`form_type`, `filing_date`, `event_date`, `filer_cik`, `position`, `holder_name`, `holder_cik`,
`holder_type` (IA investment adviser, IN individual, CO corporation...), `shares`, `percent`
(of the class, as reported), `source_url` (the filing).

### graph_source_state

When a company's `subsidiaries`, `holders` or recent `insiders` were last read from EDGAR, with
`status` (ok, none, failed). The API rereads sources older than seven days for keyed callers.

## ipo_terms (launch plan F-02)

Deal terms read from a company's prospectuses: its final prospectus (424B4), its latest S-1/A or
F-1/A (the price range) and its first S-1/F-1. Rules on the cover page and the Underwriting
section (`app/services/ipo_terms.py`), never a model. `terms` is JSON: per field `value`,
`evidence` (the verbatim sentence or table row) and `derived`.

| Field | From |
| --- | --- |
| `price_low`, `price_high` | "offering price ... between $X and $Y" (registration amendment) |
| `price_final`, `currency` | "initial public offering price per share is $X", cover table |
| `shares_offered`, `shares_primary`, `shares_secondary` | cover heading; "we are selling N shares"; "selling stockholders ... N shares" |
| `gross_proceeds`, `underwriting_discount_per_share`, `underwriting_discount_total` | cover table rows |
| `exchange`, `ticker` | "list ... on the Nasdaq Global Select Market under the symbol" |
| `underwriters`, `lead_underwriters` | Underwriting table; "... are the representatives of the underwriters" |
| `lockup_days`, `lockup_days_max` | the period most often stated for lock-up agreements, and a longer one stated with it |
| `closing_date` | "expect to deliver the shares ... on or about" |
| `lockup_expiry`, `quiet_period_end` | derived: prospectus date plus lock-up days; plus 25 days (FINRA Rule 2241) |

The prospectus's cover page is kept as `filing_sections.item = 'pr:cover'`. Read by the hourly
tracker when a 424B4, S-1/A or F-1/A arrives, and by `scripts/read_ipo_terms.py`. Shown on
`/v1/ipos` (`terms`), the MCP tool `companies_going_public`, `/v1/public/ipos` (price fields)
and the company page overview (`ipo_terms`).

## dividend_facts (Q-04): a known exception to the mapping

Dividends declared per share (`CommonStockDividendsPerShareDeclared`, else IFRS
`DividendsRecognisedAsDistributionsToOwnersPerShare`, else `CommonStockDividendsPerShareCashPaid`,
else partnerships' distributions declared or paid per unit; Q-04c, each row's basis named in the
API), every filing's observation, with the same columns,
period classes, fiscal labels and quality flags as `financial_facts`, because the same normalizer
(`normalize_company_facts(..., concepts=DIVIDEND_CONCEPTS)`) and upsert write it. **Why a table of
its own:** adding the metric to the mapping meant a version bump (1.5.0 to 1.6.0) and a re-map of
every fact, so it was kept apart; a later mapping 1.6.0 can fold it into `financial_facts`
(metric `dividends_per_share`). Loaded from the bulk company facts
(`scripts/load_dividend_facts.py`, with `--since-bulk` for companies ingested after the bulk file
was published, from the cache), then kept current by the company ingest in the same transaction
as the facts. Read by `/v1/companies/{cik}/dividends` (docs/contracts/dividends.md). Dividends per
share are the one per-share value a quarter may be derived from (`ADDITIVE_PER_SHARE`).

## insider_activity (launch plan F-03)

Insider activity found by rules in the loaded Forms 4 (`app/services/insider_activity.py`);
information about what insiders did, never a recommendation.

| Type | Rule |
| --- | --- |
| `sec.insider_cluster_buy` | three or more insiders bought in the open market (code P) within 30 days; one event per cluster, at the third insider's filing |
| `sec.insider_first_buy` | an insider's first open-market purchase at the company in two years or more, only where the loaded data reaches two years back |
| `sec.insider_large_sale` | an officer or director sold $1 million or more in one filing, and the filing says it was not under a Rule 10b5-1 plan (filings without the checkbox are not judged) |

`owners` and `detail` are JSON (insiders, values, the previous purchase). Backfill
(`scripts/detect_insider_activity.py`, or a company first seen by the tracker) is stored with
`stream_status=skipped`; activity in Forms 4 the hourly tracker loads later is published to the
feed (kind `insider`), type watches and MCP. Public: `/v1/public/insider-activity`; the company
overview's `insider_activity`.

**Trades as amended (049fef3, 2026-11-25).** The rules read each Form 4 as its Forms 4/A amend
it: a paired 4/A never counts on its own; one that restates the trade in full (same code, at
least as many lines, pairing with one original) gives its figures and dates and adds the owners
it lists; one of 0 shares cancels the trade. Partial or ambiguous 4/As leave the original as
filed.

**Joint filers are one buyer (F-03b, 2026-11-25).** For cluster buying, the reporting owners of
one Form 4 (a fund, its general partner, its manager) are one buyer, and so is every entity that
ever files together with them at the issuer (one group); `detail.insiders` counts buyers, and a
cluster needs three buyers filing apart. Stored clusters that counted joint filers separately
were retracted ("joint filers counted as separate buyers…") or updated in place.

**Affiliates filing apart are one buyer (F-03d, 2026-11-25).** Owners at the issuer also join one
buyer when: two entities' names share their first two significant words (generic words such as
LP, LLC, Fund, Partners, Management, Capital, Holdings and Roman numerals do not count: "GENERAL
ATLANTIC, L.P." and "GENERAL ATLANTIC GENPAR (BERMUDA), L.P."); an individual, himself a
reporting owner at the issuer, signs an entity's form in a control capacity (managing member,
general partner, manager, sole member, managing partner, president, CEO, a principal), or a
remark or footnote names him in one; or an entity is named in full in another entity's footnote
or remark that states control ("The sole member of ASOF Investment Management is Ares
Management LLC") or that it files a separate Form 4. Never by attorney-in-fact, power of
attorney (also "P.O.A.") or proxy signatures, never by a bare "By:" without a capacity, never
by surname alone. The signatures, remarks and footnotes are `insider_filing_text`, loaded from
the SEC insider data sets for filings with an entity owner (`scripts/load_insider_filing_text.py`;
40,965 filings, 30 checked against the XML, 30 right). Forms read as filed after the data sets
store theirs at ingest (F-03e: `insiders.store` writes the text of any form with an entity owner,
so linking keeps up with new filings); the ones read before that were filled from the document
cache (`scripts/fill_insider_filing_text.py`: 462 of 532, 70 not cached and left without text;
30 checked against the XML, 30 right). Affiliates that state no link in any of
these (Manufacturers Life and Manulife entities) still count apart. Stored clusters were
corrected through the same retract-and-update path ("affiliates counted as separate buyers…").

**Corrections, never deletions (F-03c).** `status` is `active` or `retracted`. When a rule
change means an event is no longer found, it is retracted, with `retracted_at` and a
`retraction_reason` ("counted twice: a Form 4/A repeating its original Form 4", "the trade was
cancelled by its Form 4/A", "no longer meets the rule once Form 4/A corrections are applied").
Retracted events leave the feed, type watches, timelines, the company overview, the public strip,
the screener's `cluster` and chat. An event found with another date, value or owners is updated in
place, with `corrected_at` and `previous_values` (what it said before: `activity_date`, `owners`,
`detail`); one found only now is added as backfill (`skipped`, never notified). Every event
carries `status`, and when it applies `retracted_at`, `retraction_reason`, `corrected_at` and
`previous_values`. Run once for 049fef3 by `scripts/correct_insider_activity.py` (dry run first;
a dump of `insider_activity` and `notification_deliveries` beforehand).

## company_lei, lei_overrides (launch plan K-01)

An SEC filer's LEI and, through it, its listings in Europe, the UK and Canada
(`app/services/identity.py`). Evidence, strongest first: a hand-checked `lei_overrides` row
(which may also record "no LEI"); the LEI in the SEC's record (`sec`, high); the GLEIF name equal
after removing legal-form words and the GLEIF jurisdiction equal to the SEC state of
incorporation (`name_jurisdiction`, high); the full legal name equal, legal form included, unique
among issuers, and both in or both outside the US (`name_unique`, medium). From the GLEIF golden
copy (K-01b/c): `gleif_name_jurisdiction` (high), `gleif_name_unique` and `gleif_normalised_name`
(high when the jurisdiction is exact, else medium). K-01d: `gleif_name_us_state_differs`
(medium) for a US filer whose SEC state differs from GLEIF's (the SEC often records the home
state, GLEIF the state of incorporation): only when one active US entity has the normalised
name, its headquarters or legal address is in the filer's business city, and no other filer
holds the LEI (hand-check: 30 of 30 right). Everything else stays unmatched. Rebuilt by `scripts/match_identifiers.py` and the daily listings job. Shown as
`identity` on the company overview, a line on `/profile`, and `sec_cik` on
`/v1/markets/issuers/{lei}`. Coverage follows the listings data: shares on the 38 covered venues,
so most links are foreign private issuers that also file with the SEC.

## dated_events (sec.lockup_expiry)

Events on a date rather than in a filing (`app/services/dated_events.py`): today an IPO's
lock-up ending, derived from its final prospectus (`ipo_terms.lockup_expiry`). The hourly filings
tracker creates them when the date arrives; one reached today or yesterday is published to the
feed (kind `calendar`) and type watches, an older one found the first time is backfill
(`stream_status=skipped`). Shown in the event lists and the company overview.

## edgar_feed, job_state (filings tracker, ADR 0012)

### edgar_feed

Every filing EDGAR listed, one row per filing per company it names: `accession_number`, `cik`,
`company_name` and `form_type` as EDGAR lists them, `role` (filer, subject, issuer, or listed for
daily-index rows), `filing_date`, `accepted_at` (feed rows only), `source` (search, latest,
daily-index), `seen_at`. `status` says what the tracker did: refreshed (a covered company),
discovered (added to coverage), ignored, failed (retried up to three times), or new (waiting for
the next run); `detail` holds the error of a failed row.

### job_state

A scheduled job's progress marker by `name`, such as `filings_tracker.daily_index`: the last
daily index read.

## mart_company, mart_filing_activity (quick answers)

Precomputed by `app/services/marts.py` (`scripts/build_marts.py`; a company's row is refreshed
after it is ingested). Nothing here is new data: every value is copied from `filings` or
`financial_facts` with its accession number and filing link.

**Reporting currency (D-04, 2026-11-22).** `mart_company.reporting_currency` and
`mart_company_period.currency` are each company's reporting currency: the currency of its latest
annual period of the mart metrics; where a convenience translation shares that period (TSMC's
USD figures beside TWD), the currency with more years wins, then USD. `latest_revenue`,
`latest_annual`, `revenue_history` and the company years are in that currency (before, the marts
kept USD only, so SAP showed its FY2017 USD convenience translation as its latest revenue).
Comparisons across companies stay in one currency: peers rank by size within the company's
currency and fill with unranked same-SIC companies in other currencies when fewer than four;
chat rank answers and the $1B cohorts use USD reporters; nothing is converted.

| Column | Meaning |
| --- | --- |
| `first_filing_date`, `latest_filing_date`, `filings_last_12_months`, `active` | Filing history among the filings loaded here; active means a filing in the last 12 months |
| `first_registration_date`, `first_registration_form` | First S-1 or F-1 loaded for the company |
| `ipo_prospectus_date`, `_accession`, `_url` | First final prospectus (424B4). With a registration in the two years before it, the chat counts the company as having gone public then |
| `latest_annual_report_date`, `_form` | Latest 10-K, 20-F, 40-F or 10-KT |
| `latest_revenue`, `latest_revenue_period_end` | Latest reported annual revenue in USD (indexed for rankings) |
| `latest_annual` | JSON: the latest annual value of each of the five metrics, with its filing |
| `revenue_history` | JSON: up to five fiscal years of revenue, newest first, each with its filing |

`mart_filing_activity` has one row per month and form type: `filings` and distinct `companies`.

`mart_financials` (ADR 0009): one reported value per `cik`, `metric`, `period_class` (annual or
quarterly), `unit` and `period_end`, the annual report's observation first. Each row also has
`period_start`, `value`, `currency`, the fiscal labels `fiscal_year` and `fiscal_quarter` (from
`app/services/periods.py`, named by the period end and the company's year end), `form_type`,
`filed_date`, `accession_number`, `source_tag`, `source_url`, `quality_status` and
`mapping_version`. Derived quarters are not stored.

`mart_company_period`: one row per `cik` and `fiscal_year`, with `period_end` and the five
annual USD figures as columns, plus `sources` (JSON: each figure's filing link). Exported by
`GET /v1/exports/company-years`.

`company_aliases` (issue #3, step 2): other names a company is found by, one row per `cik`
and `alias`, with `kind` (`former`: a name the SEC lists as the company's former name) and the
dates it was used (`valid_from`, `valid_to`). Ingestion replaces a company's former names from its
submissions; `scripts/load_aliases.py` fills them from the submissions archive without SEC
requests. Company search matches them as `match_type: "former_name"`.

`company_documents` (issue #3): readable documents per company, one row per `cik` and `kind`.
Today the only kind is `profile`: `title` (the company's display name), `markdown` (identity,
latest annual figures, revenue by fiscal year, going public, leadership changes in the last two
years, the risk factor categories of the latest prospectus read here, recent filings; every
figure links to its filing on sec.gov) and `built_at`. On
PostgreSQL a stored `search_vector` (tsvector of title and markdown, GIN-indexed) lets
`GET /v1/search` find companies by the words of their profiles. Rebuilt by
`scripts/build_marts.py` and after each company ingestion.

## ingestion_runs

Counts and status (`running`, `succeeded`, `partial`, `failed`) per ingestion pass, with a
redacted `error_summary`.

## api_keys, api_usage, audit_events

Keys store a prefix and a peppered SHA-256 hash only. `api_usage` has one row per
authenticated request with `route_template`, status, `response_bytes`, and `export_rows` for
exports. `audit_events` records key creation/revocation and watch changes.

## company_watches, listing_watches, notification_deliveries

A company watch binds an API key to a CIK and a destination. A listing watch (ticket 09) binds it
to listing events in a scope: `scope_type` `mic`, `country` or `region` with its `scope_value`
(`XPAR`, `FR`, `europe`), and `event_types` (comma-separated: `new_listing`, `ipo`, `delisting`,
`suspended`, `reinstated`, `modified`). Both count toward the plan's active-watch limit. Webhook
secrets are derived from `WEBHOOK_SIGNING_SECRET` and the watch id (only the hash is stored).

A delivery is one event for one watch: `watch_id` and `filing_id` for a filing, or
`listing_watch_id` and `listing_event_id` for a listing event. It has a stable `event_id`
(`evt_` + hash of the watch and the filing accession or listing event key) and a status of
`pending`, `retrying`, `delivered` or `failed`. Listing payloads carry `event_type`
`listing.<type>` and the instrument, venue, country, region and event details; never the
register file URL.


### Filing event types (launch plan D-05)

`app/services/filing_events.py`. Every new filing on the feed and in webhooks carries
`event_types` (and `event_labels`): what it means, from its form type and the 8-K items the
filer declared. Nothing is read from the text and nothing is inferred.

| Type | From |
| --- | --- |
| `sec.ipo_priced` | the company's first 424B4 after its registration (not a follow-on): `filings.event_tags`, set at ingestion and by `scripts/build_marts.py` |
| `sec.restatement` | 8-K item 4.02 (non-reliance on earlier financial statements) |
| `sec.auditor_change` | 8-K item 4.01 |
| `sec.bankruptcy` | 8-K item 1.03 |
| `sec.material_agreement` | 8-K item 1.01 |
| `sec.acquisition_completed` | 8-K item 2.01 |
| `sec.change_in_control` | 8-K item 5.01 |
| `sec.results` | 8-K item 2.02 |
| `sec.shareholder_vote` | 8-K item 5.07 |
| `sec.late_filing` | NT 10-K, NT 10-Q, NT 20-F (and amendments) |
| `sec.deregistration` | Form 15 (15-12B, 15-12G, 15-15D, 15F-*) |
| `sec.delisting` | Form 25 and 25-NSE (filed by the exchange under the issuer's CIK) |
| `sec.tender_offer` | SC TO-T (third-party tender offer) |
| `sec.merger_proxy` | DEFM14A, DEFM14C |

`company_watches.event_types` (comma-separated, null = every new filing) limits a watch to
filings carrying one of them. `GET /v1/events?event_type=sec.restatement,...` filters the feed;
`sec.officer_change` selects officer changes. Backfill never notifies (ADR 0004).


### type_watches (launch plan T-01)

Filing event types across companies, Builder plan and up; one counts as one watch. Optional
universe: `sic_prefix`, `exchange`, `filer_category`, or `ciks` (up to 500). `delivery_mode` is
`immediate` (one signed webhook per filing) unless the watch has a high-volume type
(`sec.results`, `sec.material_agreement`, `sec.shareholder_vote`) and no universe; then it is
`hourly`, and the hour's filings arrive in one webhook of type `sec.filing.batch`.
`notification_deliveries.type_watch_id` links its deliveries. Backfill never notifies.
## registrant_successions (launch plan K-05)

A company continuing under a new registrant (a new holding company, a redomicile): one row per
`predecessor_cik` and `successor_cik`, with `effective_date` (the successor's 8-K12B or 8-K12G3),
`evidence_accession` and `evidence_form`, the predecessor's exit filing (`predecessor_accession`,
`predecessor_form`: Form 25 or 15, or 8-K item 3.01, 3.03 or 2.01 from 3 days before to 30
after), `match_method` (`successor_filing_name`: the names agree once legal-form words are
removed and exactly one company qualifies) and `confidence`. A detected pair is stored only once
reviewed in `app/data/successions_reviewed.csv`, with the sentence that shows it (`quote`,
`quote_url`): `holding_company_reorganization` (high) when the successor's report describes a
holding company reorganisation or redomicile, `accounting_predecessor` (medium) when a merger's
report names the predecessor as the accounting acquirer; a merger whose accounting acquirer was
another company is rejected (Six Flags 2024: Cedar Fair; Baker Hughes 2017: GE Oil & Gas). Of
23 pairs found in ten years, 12 are stored. Facts stay under the CIK that filed
them. The overview joins the predecessors' annual figures at query time: every statement cell and
year carries `registrant_cik` and `predecessor` (with `registrant_label`, "Reported by predecessor
registrant (CIK 34088)", on a predecessor's rows); the company's own filing wins for a fiscal year
both report. `company.predecessors` and `company.successor` link the two pages with the evidence
filing. Point in time: rows count by their own filing date, so before the change the
predecessor's rows are the ones shown. Filled by `scripts/detect_successions.py`.

## company_segments (launch plan E-4, first pass)

Revenue and segment profit by business segment, geography and product, per annual report and
fiscal year, from the num and dim tables of the SEC's Notes data sets (companyfacts leaves out
dimensional facts). `kind`: business (the segment axis, alone or with
ConsolidationItems=OperatingSegments), geographic (the geographical axis), product (the product
or service axis). `role`: segment, reconciling (corporate, intersegment eliminations,
reconciling items on the ConsolidationItems axis or as a segment member) or consolidated (the
same tag without dimensions). `member` is the axis=member string, the stable key; `label` is made
from the member name. Metrics: revenue (the first revenue tag the segments use), operating income,
pretax income (banks' segment profit). A subtotal member (the sum of two or more others, such as
Apple's "Product") is dropped when the segments then add up. `status` per kind, metric and year:
ok when the segments add up to the consolidated figure within 1% or a reconciling item is tagged,
otherwise unreconciled (still shown). Overview `segments` and `GET /v1/companies/{cik}/segments`:
the latest annual report, each kind with up to three fiscal years, share of revenue, reconciling
items and the filing; point in time by filing date. Filled by `scripts/load_segments.py`.

## company_auditors (launch plan E-3)

The audit firm tagged on each annual report's cover (10-K, 20-F, 40-F and amendments, since
2021): `auditor_name`, `pcaob_firm_id` (the PCAOB firm ID, leading zeros dropped),
`auditor_location`, with the report's `form_type`, `fiscal_year`, `period_end`, `filed_date`.
Source: the txt and sub tables of the SEC's Financial Statement and Notes data sets
(`scripts/load_auditors.py`). Only the registrant's own facts (no dimension, no co-registrant).
A report filed after a change of auditor names both firms in separate contexts;
`audited_through` is each context's end date, and the current firm is the one that audited the
report's own period. Overview `auditor`: `current` (firm, since which fiscal year, latest
report), `history` (runs of consecutive reports per firm, newest first) and `changes` (8-K item
4.01 filings), point in time by filing date. Engagement partners (PCAOB Form AP) are not
included: the AuditorSearch download is behind a browser challenge.

## first_reported (launch plan E-2)

A 10-Q or 10-K figure that an 8-K item 2.02 earnings release (exhibit 99.1) stated earlier, with
the same value: `release_accession`, `release_filing_date`, `release_url` (the exhibit),
`stated_as` (dollars, thousands, millions, billions, per share) and `evidence` (the line). Rules:
the release prints the value rounded at its precision (losses in parentheses), with at least
four digits (per-share amounts to the cent), on a line labelled for the metric (a table row's
label, or the 80 characters before the number in a paragraph); only for the period the 10-Q or
10-K covers (its report period; comparatives were known from their own filing); the earliest
release filed after the period end and by the filing date wins. Metrics: revenue, gross profit,
operating income, net income, EPS basic and diluted, operating cash flow, total assets, cash,
stockholders' equity. `as_of` counts a matched figure from the release date; facts carry
`first_reported`. Filled by `scripts/read_releases.py`. A dry run on AAPL, MSFT, JPM and DUK
(last four releases each) matched 102 of 122 figures with none wrong; misses are figures a
release does not print (JPM's balance sheet is in a separate supplement).

## schedule_13d_purposes (Q-07 activist stakes)

One row per structured Schedule 13D or 13D/A (December 2024 on), from its XML on Archives, as
filed: `purpose` (Item 4, Purpose of Transaction, `transactionPurpose`, whitespace collapsed;
null when the filing leaves it out), `class_title` (`securitiesClassTitle`), `amendment_number`
(`amendmentNo`), `subject_cik` (the issuer named in the XML) and `source_url` (the XML). Loaded by
`scripts/load_13d_purposes.py` from the document cache; new 13Ds read for the holders view store
it too. Stake figures stay in `beneficial_owners`. Read by `/v1/companies/{cik}/activists` and
`/v1/activists` (docs/contracts/activists.md), which quote Item 4 and never summarise it.

## Institutional ownership: filings_13f, holdings_13f, issuer_cusips (launch plan E-1)

Source: the SEC's Form 13F data sets (sec.gov/data-research/sec-markets-data/form-13f-data-sets),
one zip of tab-separated files per three months of filing dates, loaded by
`scripts/load_13f.py`. `job_state` `13f:loaded_through` is the last filing date the loaded data
sets cover.

**filings_13f**: one row per 13F filing: `accession_number`, `filer_cik` (the manager), `filer_name`
as filed on the cover page, `report_period` (quarter end), `filing_date`, `form_type` (13F-HR,
13F-HR/A, 13F-NT), `amendment_type` (RESTATEMENT or NEW HOLDINGS; an amendment that does not say
is treated as a restatement), `report_type`, `entry_total`, `value_total_usd`,
`confidential_omitted`, `source`. The manager's address is not stored.

**holdings_13f**: a manager's position in one security on one filing, summed over the filing's
rows (investment discretion, other managers): `shares`, `value_usd`, `title_of_class`. Shares
only: amounts in principal (PRN) and put or call options are left out. Values are dollars;
filings made before 2023-01-03 reported thousands and are multiplied by 1,000.

**issuer_cusips** (internal; never in a response): which company a CUSIP belongs to.
`method` is `schedule_13dg` (issuer CIK and CUSIP on a structured Schedule 13D or 13G), `isin`
(a US or CA ISIN of a listing whose LEI is linked to the CIK) or `issuer_prefix` (another share
class of a mapped issuer with the same 6-character issuer number that Forms 13F title as a share
class; never a preferred, warrant, unit, right, note or ADR), or `13f_issuer_name` (the dominant
13F issuer name equals the company's name, uniquely, with enough managers agreeing; it also takes
American depositary shares and a partnership's units, never fund or trust units; a name whose key
is under four characters only on the exact legal name of exactly one company). The issuer-prefix
rule judges a CUSIP on all its 13F lines: 15% of lines naming another security (preferred,
depositary, perpetual, warrant, CW, right, unit, note) keep it out, so does a letter in the issue
number (a debt issue), and so do lines worth under 10% a share of the company's other mapped common
in the latest quarter with three lines on each side (also applied to the 13F-name rule).
Links removed by hand are listed with their reason, without CUSIPs, in
`app/data/cusip_removals_reviewed.csv` (`scripts/load_13f.py --remove-reviewed`). A mapping
changes only for a stronger source or the same source in a later filing.

**Overview `ownership` and `GET /v1/companies/{cik}/ownership`**: the latest complete quarter
(its 45-day filing deadline passed, and the loaded data reaches it). Per manager and quarter,
filings count in filing order: an original or a restatement replaces, NEW HOLDINGS adds; with
`as_of`, only filings made by then. `holders_count` counts managers with a position;
`flows` compares each manager with the quarter before (`exited` only for managers that filed
for the quarter without a position). `institutional_pct` is derived: 13F shares held divided by
the cover-page shares outstanding, given only for a single share class. Holders are ranked by
value; each links its 13F filing. `classes` lists the share classes counted (`title` as Forms 13F
give it, `class_label` a plain label from a reviewed map such as "Common stock", "Common units",
"Class A common stock", "Ordinary shares" or "American depositary shares", else the title as
filed, `held_as` `shares` or `adr`, `ratio` 1 or null): for American depositary shares the
number of shares one ADS represents is not on Form 13F, so `ratio` is null, and while ADR positions
are counted `institutional_pct`, `pct_of_outstanding` and `shares_outstanding` are null and a note
says why.

## International listings (ADR 0006)

### markets
One row per covered venue: `mic` (ISO 10383), `operating_mic`, `name`, `country`, `region`
(`canada`, `europe`, `uk`), `source` adapter, `source_url`.

### issuers
`lei` (unique when known), `legal_name`, `country`, `jurisdiction`, `registration_status`
(GLEIF: ISSUED, LAPSED, …), `source` (`gleif` once enriched; `gleif_isin_map` for an issuer
found through the ISIN-LEI mapping and not yet read from GLEIF), `first_detected_at`,
`updated_at`. GLEIF records are read in batches of 200 and re-read after
`MARKETS_GLEIF_REFRESH_DAYS` (30), so renames and lapsed registrations show.

### listed_instruments
One row per instrument on one venue. `listing_key` is the ISIN when the source provides a
valid one, else `SYM:<symbol>` (Canadian exchange feeds carry no ISIN). Fields: `isin`,
`symbol`, `issuer_name` (instrument full name from FIRDS until GLEIF supplies the legal name),
`issuer_lei` (from the register, else from GLEIF's daily ISIN-LEI mapping), `short_name`, `cfi_code`, `instrument_type` (`share`, `preferred_share`,
`listing` when the source does not say), `currency`, `admission_requested_date`,
`admission_approved_date`, `issuer_requested` (FIRDS `IssrReq`: the issuer asked for admission to
this venue, as for a primary listing, rather than the venue or a member admitting an instrument
listed elsewhere; null where the source does not say), `first_trade_date`, `termination_date`,
`status` (`listed`,
`delisted`, `suspended`), `source`, `source_url` (the register file or feed URL),
`source_record_hash`, `source_published_at`, `first_detected_at`, `last_seen_at`,
`processed_at`, `quality_status` (`partial` when ISIN or first-trade date is missing).

### listing_events
Idempotent per (`listing_key`, `mic`, `event_type`, `event_date`). `event_type` is one of
`new_listing` (first-trade date within 45 days of detection; `details.first_listing_for_issuer_in_our_data`
says whether this service knew other listings of the issuer, which is **not** an IPO
determination; `details.issuer_requested` and `details.likely_primary_listing`, true when the
issuer requested admission and it is the issuer's first listing in our data), `ipo` (only when a source states it), `delisting` (termination date set or
passed), `suspended`, `reinstated`, `modified` (name or symbol change, with before/after in
`details`). Dates older than the window seen for the first time are backfill and raise nothing.

### market_source_files
Register files already processed per source, so a delta is parsed once; `status` done or
failed with a redacted error.
