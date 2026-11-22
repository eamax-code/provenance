"""State of incorporation from the company's own cover tag
(dei:EntityIncorporationStateCountryCode), never a co-registrant's, and kept over the SEC
submissions field (HubSpot: NY there, DE on its 10-K cover)."""

from __future__ import annotations

import zipfile
from datetime import UTC, datetime

from app.db.models import Company, utcnow
from app.services import auditors, ticker_history
from app.services.ingestion import CompanyRecord, upsert_company

SUB = "adsh\tcik\tname\tform\tperiod\tfy\tfp\tfiled"
TXT = ("adsh\ttag\tversion\tddate\tqtrs\tiprx\tlang\tdcml\tdurp\tdatp\tdimh\tdimn\tcoreg\t"
       "escaped\tsrclen\ttxtlen\tfootnote\tfootlen\tcontext\tvalue")  # fmt: skip
HUBS, AEP = "0001193125-26-418574", "0000004904-26-000013"


def _txt(adsh, tag, value, dimn="0", coreg=""):
    return "\t".join((adsh, tag, "dei/2025", "20251231", "0", "0", "en-US", "32767", "0", "0",
                      "0x0", dimn, coreg, "0", "1", "1", "", "0", "c1", value))  # fmt: skip


def _zip(tmp_path):
    sub = [SUB, "\t".join((HUBS, "1404655", "HUBSPOT INC", "10-Q", "20260930", "2026", "Q3",
                           "20261009")),
           "\t".join((AEP, "4904", "AMERICAN ELECTRIC POWER CO INC", "10-K", "20251231", "2025",
                      "FY", "20260220"))]  # fmt: skip
    txt = [TXT, _txt(HUBS, "EntityIncorporationStateCountryCode", "DE"),
           _txt(AEP, "EntityIncorporationStateCountryCode", "NY"),
           # a co-registrant's own cover tag, on a dimension: never the parent's, never stored
           _txt(AEP, "EntityIncorporationStateCountryCode", "OH", dimn="1",
                coreg="OhioPowerCompany")]  # fmt: skip
    path = tmp_path / "2026_10_notes.zip"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("sub.tsv", "\n".join(sub) + "\n")
        z.writestr("txt.tsv", "\n".join(txt) + "\n")
    return path


def _company(db, cik, name, state):
    db.add(Company(cik=cik, legal_name=name, state_of_incorporation=state,
                   state_of_incorporation_source="submissions", source_url="https://www.sec.gov/",
                   quality_status="ok", first_detected_at=utcnow()))  # fmt: skip


def test_the_cover_tag_wins_and_a_co_registrants_tag_is_never_used(db, tmp_path):
    _company(db, "0001404655", "HUBSPOT INC", "NY")
    _company(db, "0000004904", "AMERICAN ELECTRIC POWER CO INC", "NY")
    _company(db, "0000073986", "OHIO POWER CO", "OH")
    db.commit()
    _, rows = auditors.parse_notes_zip(_zip(tmp_path))
    assert ticker_history.apply_incorporation(db, rows) == 2
    hubs = db.get(Company, db.query(Company.id).filter(Company.cik == "0001404655").scalar())
    assert hubs.state_of_incorporation == "DE"
    inc = ticker_history.incorporation(hubs)
    assert inc["source"] == "dei:EntityIncorporationStateCountryCode"
    assert inc["accession_number"] == HUBS and inc["source_url"].startswith("https://www.sec.gov/")
    aep = db.query(Company).filter(Company.cik == "0000004904").one()
    assert aep.state_of_incorporation == "NY"  # its own undimensioned tag, not Ohio Power's OH
    ohio = db.query(Company).filter(Company.cik == "0000073986").one()
    assert ohio.state_of_incorporation_source == "submissions"  # untouched by the parent's file
    # a later refresh from the SEC submissions feed does not put NY back
    upsert_company(db, CompanyRecord(
        cik="0001404655", legal_name="HUBSPOT INC", ticker="HUBS", exchange="NYSE", sic_code=None,
        sic_description=None, entity_type="operating", state_of_incorporation="NY",
        fiscal_year_end="1231", source_url="https://www.sec.gov/"), datetime.now(UTC))  # fmt: skip
    db.commit()
    again = db.query(Company).filter(Company.cik == "0001404655").one()
    assert again.state_of_incorporation == "DE"
    sub_only = ticker_history.incorporation(ohio)
    assert sub_only["source"] == "sec_submissions" and sub_only["source_url"] is None
