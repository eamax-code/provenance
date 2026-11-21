"""K-01: SEC filers linked to their LEI and listings, with match method and confidence."""

from __future__ import annotations

from datetime import date

from app.db.models import Company, Issuer, LeiOverride, ListedInstrument, Market, utcnow
from app.services import identity


def _company(db, cik, name, state=None, lei=None):
    db.add(Company(cik=cik, legal_name=name, state_of_incorporation=state, lei=lei,
                   quality_status="ok", source_url="https://www.sec.gov/",
                   first_detected_at=utcnow()))  # fmt: skip


def _issuer(db, lei, name, jurisdiction):
    db.add(Issuer(lei=lei, legal_name=name, country=jurisdiction[:2], jurisdiction=jurisdiction,
                  source="gleif", first_detected_at=utcnow()))  # fmt: skip


def test_strict_names_and_sides():
    assert identity.strict_key("Banco Santander, S.A.") == identity.strict_key("BANCO SANTANDER SA")
    assert identity.strict_key("UNILEVER N V") != identity.strict_key("UNILEVER PLC")
    assert identity.strict_key("Titan Holdings Corp.") != identity.strict_key("Titan")


def test_normalize():
    assert identity.normalize("Apple Inc.") == identity.normalize("APPLE INC") == "apple"
    assert identity.normalize("AT&T Inc.") == "at and t"
    assert identity.normalize("SAP SE") == "sap"


def test_matching_rules_and_listings(db, client, auth):
    _company(db, "0000320193", "Apple Inc.", "CA")
    _company(db, "0000000001", "Widget Corp", "DE")
    _company(db, "0000000002", "Common Name Inc", "DE")
    _company(db, "0000000003", "Has Lei Inc", lei="5493000000000000SEC1")
    _company(db, "0000000004", "Overridden Inc")
    _issuer(db, "HWUPKR0MPOU8FGXBT394", "APPLE INC.", "US-CA")
    _issuer(db, "549300WIDGET00000001", "WIDGET CORPORATION", "US-NV")  # other state: medium
    _issuer(db, "549300COMMON00000001", "Common Name, Inc.", "US-NY")
    _issuer(db, "549300COMMON00000002", "COMMON NAME INC", "US-TX")  # two: no match
    db.add(LeiOverride(cik="0000000004", lei="549300OVERRIDE000001", note="checked by hand"))
    if not db.query(Market).filter_by(mic="XETR").first():
        db.add(Market(mic="XETR", name="Xetra", country="DE", region="europe", source="seed",
                      source_url="https://registers.esma.europa.eu/"))  # fmt: skip
    db.flush()
    db.add(ListedInstrument(
        listing_key="US0378331005:XETR", isin="US0378331005", mic="XETR", issuer_name="APPLE INC",
        issuer_lei="HWUPKR0MPOU8FGXBT394", status="active", first_trade_date=date(2012, 1, 2),
        currency="EUR", source="esma_firds", first_detected_at=utcnow(), last_seen_at=utcnow(),
        processed_at=utcnow(), source_url="https://registers.esma.europa.eu/",
        source_record_hash="0" * 64,
    ))  # fmt: skip
    db.commit()
    counts = identity.match_all(db)
    assert counts == {"override": 1, "sec": 1, "name_jurisdiction": 1, "name_unique": 1,
                      "unmatched": 1}  # fmt: skip
    apple = identity.for_company(db, "0000320193")
    assert apple["lei"] == "HWUPKR0MPOU8FGXBT394" and apple["confidence"] == "high"
    # a US ISIN wraps the licensed CUSIP: the listing shows its venue, never the ISIN
    assert apple["match_method"] == "name_jurisdiction" and apple["isins"] == []
    assert apple["listings"][0]["isin"] is None
    assert apple["listings"][0]["venue"] == "Xetra"
    assert identity.for_company(db, "0000000001")["confidence"] == "medium"
    assert identity.for_company(db, "0000000002") is None  # ambiguous stays unmatched
    assert identity.cik_for_lei(db, "549300OVERRIDE000001") == "0000000004"
    r = client.get("/v1/markets/issuers/HWUPKR0MPOU8FGXBT394", headers=auth)
    assert r.status_code == 200 and r.json()["sec_cik"] == "0000320193"
