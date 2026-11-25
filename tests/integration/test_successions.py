"""K-05: a company that continues under a new holding company keeps one history; each row keeps
the registrant that filed it."""

from __future__ import annotations

from datetime import date

import pytest

from app.db.models import Company, Filing, utcnow
from app.services import successions

OLD, NEW = "0000320193", "0009999991"
DAY = date(2026, 7, 1)
QUOTE = "Apple Inc. completed a holding company reorganization."
REVIEWS = {(OLD, NEW): {"decision": "store", "match_method": "holding_company_reorganization",
                        "confidence": "high", "quote": QUOTE,
                        "quote_url": "https://www.sec.gov/Archives/edgar/data/9999991/x.htm"}}


def _filing(cik, acc, form, day, items=None):
    return Filing(cik=cik, accession_number=acc, form_type=form, filing_date=day, items=items,
                  source_url=f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc}-index.html",
                  first_detected_at=utcnow(), quality_status="ok")  # fmt: skip


@pytest.fixture
def reorganised(db, ingested_aapl):
    db.add(Company(cik=NEW, legal_name="Apple Holdings, Inc.", ticker="AAPL",
                   source_url="https://www.sec.gov/", first_detected_at=utcnow(),
                   quality_status="ok"))  # fmt: skip
    db.add(_filing(NEW, "0009999991-26-000001", "8-K12B", DAY, "2.01,3.03,5.03"))
    db.add(_filing(OLD, "0000320193-26-000900", "25-NSE", date(2026, 7, 2)))
    # a different company delisting the same day is not a match
    db.add(Company(cik="0009999992", legal_name="Banana Corp", source_url="https://www.sec.gov/",
                   first_detected_at=utcnow(), quality_status="ok"))  # fmt: skip
    db.add(_filing("0009999992", "0009999992-26-000001", "25-NSE", DAY))
    db.commit()


def test_name_key():
    assert successions.name_key("ExxonMobil Holdings Corp") == successions.name_key(
        "EXXON MOBIL CORP"
    )
    assert successions.name_key("Six Flags Entertainment Corp/OLD") == successions.name_key(
        "Six Flags Entertainment Corporation/NEW"
    )
    assert successions.name_key("Apple Inc.") != successions.name_key("Banana Corp")


def test_detect_and_store(db, reorganised):
    pairs = successions.detect(db)
    assert [(p["predecessor_cik"], p["successor_cik"]) for p in pairs] == [(OLD, NEW)]
    p = pairs[0]
    assert p["effective_date"] == DAY and p["evidence_form"] == "8-K12B"
    assert p["predecessor_form"] == "25-NSE"
    # nothing is stored before a review; a rejection is counted, never stored
    assert successions.store(db, pairs, {})["not_reviewed"] == [[OLD, NEW]]
    assert successions.predecessors(db, NEW) == []
    rejected = {(OLD, NEW): {**REVIEWS[(OLD, NEW)], "decision": "reject"}}
    assert successions.store(db, pairs, rejected)["rejected"] == 1
    assert successions.store(db, pairs, REVIEWS)["stored_new"] == 1
    assert successions.store(db, pairs, REVIEWS)["updated"] == 1
    assert [r.predecessor_cik for r in successions.predecessors(db, NEW)] == [OLD]
    assert successions.successor(db, OLD).successor_cik == NEW


def test_successor_overview_continues_the_history(db, reorganised):
    successions.store(db, successions.detect(db), REVIEWS)
    from app.services import company_overview

    o = company_overview.build(db, NEW)
    assert company_overview.first_filing_date(db, NEW) < DAY  # as_of reaches the old filings
    pred = o["company"]["predecessors"]
    assert pred[0]["cik"] == OLD and pred[0]["evidence"]["form_type"] == "8-K12B"
    assert pred[0]["evidence"]["source_url"].endswith("0009999991-26-000001-index.html")
    assert pred[0]["quote"] == QUOTE and pred[0]["confidence"] == "high"
    assert pred[0]["display_name"] == "Apple Inc."
    income = next(s for s in o["statements"]["sections"] if s["key"] == "income")
    cells = [c for row in income["rows"] for c in row["cells"] if c]
    assert cells and all(c["registrant_cik"] == OLD and c["predecessor"] for c in cells)
    assert cells[0]["registrant_label"] == "Reported by predecessor registrant (CIK 320193)"
    assert all(c["source_url"].startswith("https://www.sec.gov/") for c in cells)
    old = company_overview.build(db, OLD)
    assert old["company"]["successor"]["cik"] == NEW
    own = next(s for s in old["statements"]["sections"] if s["key"] == "income")
    assert all(not c["predecessor"] for row in own["rows"] for c in row["cells"] if c)


def test_the_reviewed_file_is_complete_and_quotes_every_stored_pair():
    rows = successions.reviewed()
    stored = [r for r in rows.values() if r["decision"] == "store"]
    assert len(rows) == 78 and len(stored) == 62  # K-05c: 45 joined on the successor's own filing
    # Cardtronics 2016: the earlier reject reversed on the plc's 10-Q (PM, 2026-11-25)
    card = rows[("0001277856", "0001671013")]
    assert card["decision"] == "store" and "Delaware to the United Kingdom" in card["quote"]
    assert card["note"]
    # 2026-11-24: Google Inc. -> Alphabet Inc. (its 8-K of 2015-10-02 names the successor issuer)
    assert rows[("0001288776", "0001652044")]["decision"] == "store"
    assert all(r["quote"] and r["quote_url"].startswith("https://www.sec.gov/Archives/")
               for r in stored)  # fmt: skip
    assert rows[("0000034088", "0002115436")]["confidence"] == "high"  # ExxonMobil
    assert rows[("0000884905", "0001707925")]["match_method"] == "accounting_predecessor"  # Linde
    assert rows[("0000701374", "0001999001")]["decision"] == "reject"  # Six Flags: Cedar Fair


def test_a_reviewed_named_successor_is_stored_with_its_evidence(db, reorganised):
    """K-05c: a pair the name rule cannot find (a D-01b named successor) is stored when reviewed,
    with the successor's 8-K12B as evidence and the predecessor's exit filing; a pair D-01b
    does not link is not built here."""
    from app.db.models import NamedSuccessor, RegistrantSuccession

    db.add(NamedSuccessor(predecessor_cik=OLD, successor_cik=NEW, kind="succeeded",
                          name_as_filed="Apple Holdings, Inc.", quote=QUOTE, match_method="name",
                          evidence_accession="0000320193-26-000899", evidence_form="8-K",
                          evidence_date=date(2026, 6, 30), evidence_url=REVIEWS[(OLD, NEW)][
                              "quote_url"], updated_at=utcnow()))  # fmt: skip
    db.commit()
    other = {("0009999992", NEW): {**REVIEWS[(OLD, NEW)]}}
    pairs = successions.pairs_from_reviewed(db, {**REVIEWS, **other}, known=set())
    assert [(p["predecessor_cik"], p["successor_cik"]) for p in pairs] == [(OLD, NEW)]
    p = pairs[0]
    assert (p["evidence_form"], p["effective_date"], p["predecessor_form"]) == ("8-K12B", DAY,
                                                                              "25-NSE")  # fmt: skip
    assert successions.pairs_from_reviewed(db, REVIEWS, known={(OLD, NEW)}) == []
    successions.store(db, pairs, REVIEWS)
    row = db.get(RegistrantSuccession, (OLD, NEW))
    assert row.quote == QUOTE and row.evidence_accession == "0009999991-26-000001"


def test_a_successor_section_year_never_mixes_with_the_predecessors(db, client, auth,
                                                                     reorganised):  # fmt: skip
    """K-05d: where the successor reports a section for a fiscal year (here its restated revenue),
    that section-year is its figures only: the predecessor's other income lines for the year stay
    blank with a note, its balance sheet (not reported by the successor) still fills the year, and
    the predecessor's own page keeps its as-filed figures. The statement endpoint agrees."""
    from datetime import UTC, datetime

    from app.db.models import FinancialFact
    from app.services import company_overview

    successions.store(db, successions.detect(db), REVIEWS)
    old = company_overview.build(db, OLD)
    inc_old = next(s for s in old["statements"]["sections"] if s["key"] == "income")
    year = old["statements"]["fiscal_years"][-1]
    i_old = old["statements"]["fiscal_years"].index(year)
    rev_old = next(r for r in inc_old["rows"] if r["metric"] == "revenue")["cells"][i_old]
    end = date.fromisoformat(rev_old["period_end"])
    now = datetime.now(UTC)
    db.add(FinancialFact(cik=NEW, metric="revenue", value=rev_old["value"] * 0.9, unit="USD",
                         currency="USD", period_start=date(end.year - 1, end.month, end.day),
                         period_end=end, period_type="duration", period_class="annual",
                         fiscal_year=end.year, fiscal_period="FY", form_type="10-K",
                         filed_date=date(2026, 11, 1), accession_number="0009999991-26-000050",
                         source_tag="Revenues", source_taxonomy="us-gaap",
                         source_url="https://www.sec.gov/Archives/edgar/data/9999991/x-index.htm",
                         mapping_version="1.5.0", quality_status="ok", derived=False,
                         first_detected_at=now, processed_at=now,
                         observation_key="k05d-restated-revenue"))  # fmt: skip
    ni = next(r for r in inc_old["rows"] if r["metric"] == "net_income")["cells"][i_old]
    db.add(FinancialFact(cik=NEW, metric="net_income", value=ni["value"], unit="USD",
                         currency="USD", period_start=date(end.year - 1, end.month, end.day),
                         period_end=end, period_type="duration", period_class="annual",
                         fiscal_year=end.year, fiscal_period="FY", form_type="10-K",
                         filed_date=date(2026, 11, 1), accession_number="0009999991-26-000050",
                         source_tag="NetIncomeLoss", source_taxonomy="us-gaap",
                         source_url="https://www.sec.gov/Archives/edgar/data/9999991/x-index.htm",
                         mapping_version="1.5.0", quality_status="ok", derived=False,
                         first_detected_at=now, processed_at=now,
                         observation_key="k05d-restated-net-income"))  # fmt: skip
    db.commit()
    new = company_overview.build(db, NEW)
    years = new["statements"]["fiscal_years"]
    i = years.index(year)
    inc = next(s for s in new["statements"]["sections"] if s["key"] == "income")
    col = {r["metric"]: r["cells"][i] for r in inc["rows"]}
    assert col["revenue"]["registrant_cik"] == NEW
    assert col["revenue"]["value"] == rev_old["value"] * 0.9
    assert all(c is None for m, c in col.items() if m not in ("revenue", "net_income"))
    note = next(n for n in inc["gap_notes"] if n["fiscal_label"] == year)
    assert note["predecessor_cik"] == OLD and "Apple" in note["text"]
    assert "operating_income" in note["metrics"]
    # a ratio never puts the successor's figure over the predecessor's (net income over Apple's
    # total assets for the year): blank
    ratio = next(s for s in new["statements"]["sections"] if s["key"] == "ratios")
    roa = next(r for r in ratio["rows"] if r["metric"] == "return_on_assets")
    assert roa["cells"][i] is None and roa["cells"][i - 1] is not None
    bal = next(s for s in new["statements"]["sections"] if s["key"] == "balance")
    assert {r["cells"][i]["registrant_cik"] for r in bal["rows"] if r["cells"][i]} == {OLD}
    earlier = years[i - 1]  # a year the successor does not report: Apple's figures
    assert all(r["cells"][i - 1]["registrant_cik"] == OLD for r in inc["rows"] if r["cells"][i - 1])
    assert earlier != year
    # the predecessor's own page: its as-filed revenue, unchanged
    again = company_overview.build(db, OLD)
    inc_again = next(s for s in again["statements"]["sections"] if s["key"] == "income")
    assert next(r for r in inc_again["rows"] if r["metric"] == "revenue")["cells"][i_old] == rev_old
    # the statement endpoint: the same section-year choice
    body = client.get(f"/v1/companies/{NEW}/statements/income?period=annual", headers=auth).json()
    cells = [c for row in body["rows"] for c in row["cells"]
             if c and c.get("period_end") == end.isoformat()]  # fmt: skip
    reported = [c for c in cells if not c.get("derived")]  # margins computed from these
    assert reported and {c["registrant_cik"] for c in reported} == {NEW}
