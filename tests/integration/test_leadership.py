"""K-02 and U-03: an 8-K departure ends an insider role at once; leadership by person."""

from __future__ import annotations

from datetime import date, timedelta

from app.db.models import Company, InsiderFiling, OfficerChange, utcnow
from app.services import insiders, leadership

CIK = "0000320193"
TODAY = date.today()


def _filing(db, n, owner, name, title, day, officer=True, director=False):
    db.add(InsiderFiling(
        accession_number=f"0001-26-{n:06d}", issuer_cik=CIK, owner_cik=f"{owner:010d}",
        owner_name=name, is_officer=officer, is_director=director, officer_title=title,
        form_type="4", filing_date=day, source="filing",
    ))  # fmt: skip


def _change(db, n, person, role, kind, day, effective=None, what=None):
    db.add(OfficerChange(
        cik=CIK, accession_number=f"0002-26-{n:06d}", seq=1, filing_date=day, person=person,
        role=role, change_type=kind, effective=effective, verified=True, what=what,
        source_url=f"https://www.sec.gov/Archives/edgar/data/320193/{n}/",
        extractor_version="test",
    ))  # fmt: skip


def test_keys_match_across_forms_and_8ks():
    assert leadership.key_from_filed("COOK TIMOTHY D") == leadership.key_from_text("Tim Cook")
    assert leadership.key_from_text("Luca Maestri, Jr.") == ("maestri", "l")
    assert leadership.effective_date("effective January 1, 2025") == date(2025, 1, 1)
    chair = leadership.ROLES["chair"]
    assert chair.search("Chairman and Chief Executive Officer")
    assert not chair.search("Vice Chair and President") and not chair.search("Vice-Chairman")


def test_departure_ends_the_role_and_leadership_is_by_person(db):
    db.add(Company(cik=CIK, legal_name="Apple Inc.", quality_status="ok",
                   source_url="https://www.sec.gov/", first_detected_at=utcnow()))  # fmt: skip
    _filing(db, 1, 1, "COOK TIMOTHY D", "Chief Executive Officer", TODAY - timedelta(days=30),
            director=True)  # fmt: skip
    _filing(db, 2, 2, "MAESTRI LUCA", "Senior VP, CFO", TODAY - timedelta(days=200))
    _filing(db, 3, 3, "PAREKH KEVAN", "Senior VP, CFO", TODAY - timedelta(days=20))
    _filing(db, 4, 4, "WILLIAMS JEFFREY E", "COO", TODAY - timedelta(days=10))
    _change(db, 1, "Luca Maestri", "Chief Financial Officer", "departure",
            TODAY - timedelta(days=100), "effective December 31, 2024")  # fmt: skip
    _change(db, 2, "Kevan Parekh", "Chief Financial Officer", "appointment",
            TODAY - timedelta(days=100), "effective January 1, 2025")  # fmt: skip
    leave = (TODAY + timedelta(days=60)).strftime("%B %-d, %Y")
    _change(db, 3, "Jeff Williams", "Chief Operating Officer", "retirement",
            TODAY - timedelta(days=5), f"effective {leave}")  # fmt: skip
    db.commit()
    owners = insiders.roles(db, CIK)
    leadership.apply_to_roles(db, CIK, owners)
    by = {o["name_as_filed"]: o for o in owners}
    assert by["MAESTRI LUCA"]["current"] is False  # ended by the 8-K, not by two quiet years
    assert by["MAESTRI LUCA"]["ended"]["basis"] == "8-K item 5.02"
    assert by["WILLIAMS JEFFREY E"]["current"] is True and by["WILLIAMS JEFFREY E"]["leaving_on"]
    out = leadership.overview(db, CIK, owners)
    cur = out["current_leadership"]
    assert cur["ceo"]["name"] == "Timothy D Cook" and cur["ceo"]["basis"] == "Form 4 officer title"
    assert cur["cfo"]["name"] == "Kevan Parekh" and cur["cfo"]["basis"] == "8-K item 5.02"
    assert cur["chair"] is None
    people = {p["name"]: p for p in out["people"]}
    # the Form 4 (legal) name, with the 8-K spelling as an alias
    assert people["Jeffrey E Williams"]["status"] == "leaving"
    assert people["Jeffrey E Williams"]["aliases"] == ["Jeff Williams"]
    assert people["Jeffrey E Williams"]["match"]["method"] == "name_nickname"
    assert people["Luca Maestri"]["status"] == "departed" and not people["Luca Maestri"]["current"]
    assert out["people"][0]["name"] == "Jeffrey E Williams"  # newest event first


def test_apple_cook_and_ternus(db):
    """Cook moves to Executive Chair and Ternus becomes CEO on 1 Sep 2026 (8-K 5.02); their
    Forms 4 say only since when each reports. The role start comes from the 8-K."""
    db.add(Company(cik=CIK, legal_name="Apple Inc.", quality_status="ok",
                   source_url="https://www.sec.gov/", first_detected_at=utcnow()))  # fmt: skip
    _filing(db, 1, 1, "COOK TIMOTHY D", "Chief Executive Officer", date(2022, 9, 27),
            director=True)  # fmt: skip
    _filing(db, 2, 2, "TERNUS JOHN", "SVP, Hardware Engineering", TODAY - timedelta(days=40))
    # as the extraction stores it: the role left in `role`, the new one in `what`
    _change(db, 1, "Tim Cook", "Chief Executive Officer", "role_change", date(2026, 4, 20),
            "September 1, 2026",
            "transitions from Chief Executive Officer to Executive Chair of Board")  # fmt: skip
    _change(db, 3, "Art Levinson", "Chair of the Board", "role_change", date(2026, 4, 20),
            "September 1, 2026", "becomes Lead Independent Director")  # fmt: skip
    _filing(db, 3, 3, "LEVINSON ARTHUR D", None, TODAY - timedelta(days=50), officer=False,
            director=True)  # fmt: skip
    _change(db, 2, "John Ternus", "Chief Executive Officer", "appointment", date(2026, 4, 20),
            "September 1, 2026")  # fmt: skip
    db.commit()
    owners = insiders.roles(db, CIK)
    leadership.apply_to_roles(db, CIK, owners)
    out = leadership.overview(db, CIK, owners, date(2026, 11, 22))
    cur = out["current_leadership"]
    assert cur["chair"]["title"] == "Executive Chair of Board"  # Levinson moved out of the chair
    assert (cur["ceo"]["name"], cur["ceo"]["since"], cur["ceo"]["basis"]) == (
        "John Ternus", "2026-09-01", "8-K item 5.02"
    )  # fmt: skip
    assert (cur["chair"]["name"], cur["chair"]["since"]) == ("Timothy D Cook", "2026-09-01")
    assert cur["chair"]["reporting_since"] == "2022-09-27"  # Form 4: reporting, not the role
    cook = next(p for p in out["people"] if p["name"] == "Timothy D Cook")
    assert cook["aliases"] == ["Tim Cook"] and cook["match"]["confidence"] == "high"
    assert leadership.match_people("COOK TIMOTHY D", "Tim Cook") == ("name_nickname", "high")
    assert leadership.match_people("COOK T", "Tim Cook") == ("name_initial", "medium")
    assert leadership.match_people("COOK THOMAS", "Tim Cook") is None
