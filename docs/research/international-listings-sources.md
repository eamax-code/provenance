# International listing sources: research report (verified 2026-10-22)

Goal: official, direct, free, machine-readable sources for public-company identity and listing
lifecycle (new listings, IPOs, delistings, suspensions, name changes) in Canada, the EU/EEA and
the UK, with terms that allow a small data product to use them. Every URL below was fetched on
the stated date; sample files were downloaded and inspected. Decisions feed ADR 0006.

## Summary

| Source | What it gives | Format / cadence | Terms | Decision |
| --- | --- | --- | --- | --- |
| ESMA FIRDS | Every instrument admitted to EU/EEA venues: ISIN, names, CFI, currency, issuer LEI, MIC, first-trade/termination/admission dates; daily deltas mark new, modified, terminated, cancelled | Zipped ISO 20022 XML; delta daily by 09:00 CET, full weekly | Reuse allowed with source acknowledged; no implied endorsement | **Use** (primary EU backbone) |
| FCA FIRDS | UK venues (plus mirrored EU27 data) in the same schema | Same; delta daily by 09:00 UTC, full Saturday | FCA copyright; datasets in the Data section under UK OGL; no explicit FIRDS licence | **Use**, attribute FCA, identity metadata only |
| GLEIF | Issuer legal identity by LEI: legal name, country, status; ISIN-LEI mapping | JSON:API, 60 req/min; bulk golden copy 3x daily; daily ISIN-LEI CSV | CC0 | **Use** |
| Xetra / Deutsche Börse | All tradable instruments CSV (ISIN, WKN, mnemonic, MIC, status) | CSV daily ~23:45 CET | Disclaimer only | Use with care (not needed while FIRDS covers XETR) |
| Euronext | Equities list download, IPO showcase HTML | CSV / HTML | "no user shall use any Information in any business or commercial enterprise" | Avoid for pipeline; FIRDS covers Euronext MICs |
| LSE | Instrument list Excel (stale), licensed daily report | Excel / licensed | Prohibits bots and commercial use | Avoid; FCA FIRDS covers XLON/AIM |
| SIX | IPO history JSON (no ISIN) | JSON | Reproduction for commercial purposes prohibited | Avoid; FIRDS covers XSWX |
| Nasdaq Nordic | Listing changes as PDFs | PDF | Personal, non-commercial; bans scraping | Avoid; FIRDS covers XSTO/XHEL/XCSE |
| SEDAR+ (CSA) | Issuer profiles, reporting issuer lists, CTOs | Web UI with CSV export | Forbids automated searches and building a database | **Avoid** automated use |
| OSC / BCSC / ASC / AMF | Reporting issuer lists | PDF, daily to semi-monthly | OSC under Open Government Licence Ontario; others unstated | Use with care (PDF, names only); not implemented |
| TSX / TSXV directory | Name, symbol, sub-instruments; recent / delisted / suspended lists with dates | JSON, no key, ~daily | Personal, non-commercial; no redistribution without written permission | Implemented, **disabled by default** |
| TSX monthly Excel | Listing type (IPO, graduate, CPC), listing date, sector | XLSX monthly | "Do not copy, distribute, sell or modify" | Not implemented |
| TMX Datalinx | TSXV listings changes (CTO, delist, new listing, graduation, name change) | CSV/JSON, paid | Licensed, no redistribution | Only sanctioned redistribution path; not used |
| CSE | Listed companies with status, listing date, sector, recent changes | JSON nightly, no key | Personal, non-commercial; consent required to redistribute | Implemented, **disabled by default** |
| Cboe Canada | Security master and corporate actions | Member/subscriber files | Licence agreement required | Avoid without licence |

## ESMA FIRDS (used)

- File register: `https://registers.esma.europa.eu/solr/esma_registers_firds_files/select?q=*&fq=publication_date:[<from> TO <to>]&wt=json&rows=200`; fields `file_name, file_type (FULINS|DLTINS|FULCAN), publication_date, download_link, checksum`.
- Files: `https://firds.esma.europa.eu/firds/<file>`; `DLTINS_<YYYYMMDD>_<n>of<N>.zip` (split at 500,000 records), `FULINS_<CFI letter>_<date>_<n>of<N>.zip`.
- Observed sizes: a delta part is about 13 MB zipped / 470 MB XML; equities full files about 8 + 4 MB zipped.
- Schema: `head.003` wrapper with `AppHdr/MsgDefIdr=auth.036.001.03`; payload `FinInstrmRptgRefDataDltaRpt/FinInstrm/{NewRcrd|ModfdRcrd|TermntdRcrd|CancRcrd}`; fields `FinInstrmGnlAttrbts/{Id,FullNm,ShrtNm,ClssfctnTp,NtnlCcy}`, `Issr` (LEI), `TradgVnRltdAttrbts/{Id,IssrReq,ReqForAdmssnDt,AdmssnApprvlDtByIssr,FrstTradDt,TermntnDt}`, `TechAttrbts/{RlvntCmptntAuthrty,PblctnPrd/FrDt,RlvntTradgVn}`. Full files use `auth.017` with `FinInstrmRptgRefDataRpt/RefData`.
- Semantics: `TermntnDt` 9999-12-31 means open-ended; `FrstTradDt` is per (ISIN, MIC), so a secondary-venue admission looks like a new listing; a name change is a `ModfdRcrd` with no reason code. In one delta, 500k records contained 154 equity (`ES*`) records.
- Licence (esma.europa.eu legal notice): reproduction authorised except as otherwise stated, provided the source is acknowledged, without implying ESMA endorsement.
- Adapter: `app/services/markets/firds.py` streams the XML, keeps only covered MICs and share CFI prefixes (`ES`, `EP`), and records each processed file so deltas are parsed once.

## FCA FIRDS (used)

- Register: `https://api.data.fca.org.uk/fca_data_firds_files?q=((file_type:DLTINS) AND (publication_date:[<from> TO <to>]))&from=0&size=100&sort=publication_date:asc`; download `https://data.fca.org.uk/artefacts/FIRDS/<file>` (a delta part about 95 MB).
- Content: UK venues, UK systematic internalisers, and the ESMA EU27 files mirrored. The adapter keeps only UK MICs so EU rows are not double counted.
- Terms: fca.org.uk/legal claims FCA copyright; clause 2.2 applies the UK Open Government Licence to datasets in the Data section; no FIRDS-specific licence. Attribute the FCA; keep to identity metadata.

## GLEIF (used)

- `https://api.gleif.org/api/v1/lei-records/{lei}` and `?filter[isin]=…`, `?filter[entity.legalName]=…`, `/lei-records/{lei}/isins`; JSON:API with `attributes.entity.legalName.name`, `entity.legalAddress.country`, `entity.status`, `registration.status`.
- Rate limit 60 requests per minute per user (no headers; self-throttle). Bulk: golden copy three times daily; ISIN-LEI mapping daily (~33 MB zip, 9.4 M rows).
- Licence: CC0; do not suggest GLEIF endorsement.
- Canadian coverage: about 59,000 LEI records with a Canadian legal address, 27,800 issued; ISIN coverage for equities is patchy (Shopify has an LEI but no ISIN mapping).

## Canada

- **SEDAR+** has no API, RSS or bulk feed and its terms of use forbid automated searches, building a database and commercial products. The public site sits behind bot protection. Not used; its email alerts for cease-trade orders can be used manually.
- **Provincial lists** (OSC daily PDF under Open Government Licence Ontario; BCSC, ASC, AMF PDFs) give issuer names and principal regulator only. Not implemented; a PDF parser is a possible follow-up.
- **TSX/TSXV**: `https://www.tsx.com/json/company-directory/search/{tsx|tsxv}/^*` (name, symbol, sub-instruments), `/json/company-directory/{recent|delisted|suspended}/{tsx|tsxv}` (recent and delisted carry epoch dates). No ISIN, CUSIP, LEI or listing type. Terms: view and print for non-commercial or personal use only; no distribution without written permission. The monthly Excel (listing type IPO/graduate/CPC, listing date) carries "Do not copy, distribute, sell or modify". TMX Datalinx sells the listings-changes feed with no redistribution rights.
- **CSE**: `https://thecse.com/api/webapi/listed-companies/` (symbol, name, status Active/Suspended/Halted/Delisted, listing date, security type, sector, recent symbol/name/CUSIP changes), nightly. Terms: personal, non-commercial; written consent required for redistribution.
- **Cboe Canada**: official security master and corporate-action files are available only to members and subscribers under a licence agreement.
- Decision: TSX and CSE adapters are implemented (`app/services/markets/canada.py`) but disabled by default; enabling them in `MARKETS_SOURCES_ENABLED` is the operator's statement that written permission is held. Canadian rows are keyed by symbol because the feeds carry no ISIN; GLEIF enrichment applies only where an LEI is known.

## Cross-cutting findings

- No pan-European official IPO or delisting feed exists beyond FIRDS. "First trade date" is per instrument and venue; the service therefore reports `new_listing` with a `first_listing_for_issuer_in_our_data` flag and never labels it an IPO. An `ipo` event exists only where a source states one (currently none of the enabled sources do; TSX's monthly Excel would, under licence).
- The ISO 10383 MIC list (`https://www.iso20022.org/sites/default/files/ISO10383_MIC/ISO10383_MIC.csv`, monthly) maps MICs to exchanges; the venue registry in `app/services/markets/venues.py` is a curated subset.
- Attribution text used on the site and in API notes: "Listing data from ESMA FIRDS, FCA FIRDS and GLEIF; Provenance is independent and not affiliated with ESMA, the FCA, GLEIF, the CSA, TMX, the CSE or any exchange."

Sample files inspected during research: `DLTINS_20261021_01of04.zip` (ESMA), `t7-xetr-allTradableInstruments.csv` (Xetra), TSX directory/recent/delisted/suspended JSON, CSE listed-companies JSON, GLEIF records for Canadian issuers. Trimmed copies of the real records are the test fixtures under `tests/fixtures/markets/`.
