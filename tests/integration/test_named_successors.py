"""D-01b: the successor a stopped registrant's own filings name, quoted, linked only on an exact
name (or the successor's own CIK), shown on the overview below K-05's reviewed successor."""

from __future__ import annotations

from datetime import UTC, date, datetime

from app.db.models import Company, MartCompany, NamedSuccessor, RegistrantSuccession
from app.services import named_successors as N

ON = date(2012, 4, 2)
MEDCO, ESH, ESI, OTHER, TWIN1, TWIN2 = (
    "0000000951",
    "0000000952",
    "0000000953",
    "0000000954",
    "0000000955",
    "0000000956",
)


def _companies(db):
    now = datetime.now(UTC)
    for cik, name in (
        (MEDCO, "MEDCO HEALTH SOLUTIONS INC"),
        (ESH, "Express Scripts Holding Co."),
        (ESI, "EXPRESS SCRIPTS INC"),
        (OTHER, "Callon Petroleum Co"),
        (TWIN1, "Acme Corp"),
        (TWIN2, "ACME CORP /DE/"),
    ):
        db.add(
            Company(
                cik=cik,
                legal_name=name,
                source_url="https://www.sec.gov/",
                first_detected_at=now,
                last_processed_at=now,
                quality_status="ok",
            )
        )
    db.commit()
    return N.Names(db)


def _pred(names, *paras, cik=MEDCO, own=("MEDCO HEALTH SOLUTIONS INC",)):
    return N.read_predecessor(list(paras), cik, {N.norm(n) for n in own}, names, ON)


def test_a_defined_parent_is_resolved_and_matched_exactly(db):
    names = _companies(db)
    got = _pred(
        names,
        "Effective April 2, 2012, pursuant to the Merger Agreement, by and among the "
        "Company, Express Scripts, Inc. (“Express Scripts”), Express Scripts Holding Company "
        "(f/k/a Aristotle Holding, Inc.) (the “Parent”), Aristotle Merger Sub, Inc. and "
        "Plato Merger Sub, Inc., each of Express Scripts and the Company became wholly "
        "owned subsidiaries of the Parent.",
    )
    assert (got["successor_cik"], got["kind"]) == (ESH, "acquired")
    assert got["name_as_filed"] == "Express Scripts Holding Company"
    assert got["quote"].startswith("Effective April 2, 2012") and got["quote"].endswith("Parent.")


def test_successor_issuer_and_merged_into_and_holding_company_kinds(db):
    names = _companies(db)
    got = _pred(
        names,
        "Pursuant to Rule 12g-3(a) of the Exchange Act, Express Scripts Holding "
        "Company is the successor issuer to the Company.",
    )
    assert (got["successor_cik"], got["kind"]) == (ESH, "succeeded")
    got = _pred(
        names,
        "On July 1, 2019, the Company merged with and into Callon Petroleum Company, "
        "with Callon Petroleum Company as the surviving corporation.",
    )
    assert (got["successor_cik"], got["kind"]) == (OTHER, "merged")
    got = _pred(
        names,
        "Express Scripts Holding Company (“Holdings”) became the new parent holding "
        "company. As a result, the Company became a wholly owned subsidiary of Holdings.",
    )
    assert (got["successor_cik"], got["kind"]) == (ESH, "succeeded")


def test_doubtful_names_and_subjects_link_nothing(db):
    names = _companies(db)
    # a merger subsidiary merging into the filer names no successor
    assert (
        _pred(
            names,
            "Merger Sub merged with and into the Company, with the Company as the "
            "surviving corporation.",
        )
        is None
    )
    # a name that is not exactly a company held here
    assert (
        _pred(
            names,
            "The Company became a wholly owned subsidiary of Express Scripts Holdings Group Ltd.",
        )
        is None
    )
    # two companies hold the name: ambiguous
    assert _pred(names, "The Company became a wholly owned subsidiary of Acme Corporation.") is None
    # the subject is not the filer (its operating partnership)
    assert (
        _pred(
            names,
            "As a result of the Mergers, Medco OP became a wholly owned subsidiary of "
            "Callon Petroleum Company.",
        )
        is None
    )


def test_the_successors_own_8k12b_names_its_predecessor(db):
    names = _companies(db)
    got = N.read_successor(
        [
            "This Current Report is being filed for the purpose of establishing "
            "Express Scripts Holding Company as the successor issuer to Medco "
            "Health Solutions, Inc. pursuant to Rule 12g-3(a)."
        ],
        ESH,
        {N.norm("Express Scripts Holding Co.")},
        names,
        ON,
    )
    assert (got["predecessor_cik"], got["successor_cik"], got["match_method"]) == (
        MEDCO,
        ESH,
        "filer_cik",
    )


def test_conflicting_successors_of_equal_strength_link_nothing():
    row = {
        "predecessor_cik": MEDCO,
        "match_method": "name",
        "quote": "became a subsidiary",
        "evidence_date": ON,
    }
    assert N.choose([{**row, "successor_cik": ESH}, {**row, "successor_cik": OTHER}]) == {}
    strong = {**row, "successor_cik": ESH, "quote": "X is the successor issuer to the Company"}
    assert N.choose([strong, {**row, "successor_cik": OTHER}])[MEDCO]["successor_cik"] == ESH


def test_the_overview_shows_succeeded_by_below_k05(client, auth, db):
    _companies(db)
    db.add(
        MartCompany(
            cik=MEDCO,
            legal_name="MEDCO HEALTH SOLUTIONS INC",
            periodic_active=False,
            last_periodic_form="10-K/A",
            last_periodic_date=date(2012, 4, 2),
        )
    )
    db.add(
        NamedSuccessor(
            predecessor_cik=MEDCO,
            successor_cik=ESH,
            kind="acquired",
            name_as_filed="Express Scripts Holding Company",
            quote="... the Company became wholly owned subsidiaries of the Parent.",
            match_method="name",
            evidence_accession="0001193125-12-144957",
            evidence_form="8-K",
            evidence_date=ON,
            evidence_url="https://www.sec.gov/Archives/edgar/data/1170650/"
            "000119312512144957/d8k.htm",
        )
    )
    db.commit()
    body = client.get(f"/v1/companies/{MEDCO}/overview", headers=auth).json()
    s = (
        body["company"]["succeeded_by"]
        if "succeeded_by" in body.get("company", {})
        else body["succeeded_by"]
    )
    assert (s["cik"], s["label"], s["form"], s["filed_date"]) == (
        ESH,
        "Acquired by",
        "8-K",
        "2012-04-02",
    )
    assert s["document_url"].startswith("https://www.sec.gov/Archives/")
    # K-05's reviewed successor takes precedence
    db.add(
        RegistrantSuccession(
            predecessor_cik=MEDCO,
            successor_cik=ESI,
            effective_date=ON,
            evidence_accession="0001193125-12-144950",
            evidence_form="8-K12B",
            match_method="name",
            confidence="high",
        )
    )
    db.commit()
    body = client.get(f"/v1/companies/{MEDCO}/overview", headers=auth).json()
    c = body.get("company", body)
    assert c["successor"]["cik"] == ESI and c["succeeded_by"] is None


def test_a_buyer_owned_by_a_held_companys_funds_is_not_that_company(db):
    """Everi 2025: "Voyager Parent, LLC, ... owned by funds managed by affiliates of Apollo Global
    Management, Inc. ("Buyer")" names Voyager Parent, not Apollo; a description with a legal-form
    comma is still stripped."""
    names = _companies(db)
    got = _pred(
        names,
        "The Merger Agreement is by and among the Company, Voyager Parent, LLC, a Delaware limited "
        "liability company owned by funds managed by affiliates of Express Scripts, Inc. "
        "(“Buyer”), and Voyager Merger Sub, Inc. At the Effective Time, the Company became a "
        "wholly owned subsidiary of Buyer.",
    )
    assert got is None


def test_a_merger_sub_named_after_a_term_is_not_the_term(db):
    """Duke Realty 2022: "DRE merged with and into Prologis Merger Sub" is not "merged into
    Prologis"."""
    names = _companies(db)
    got = _pred(
        names,
        "Callon Petroleum Company (“Callon”) and the Company signed the agreement. On October 3, "
        "2022, the Company merged with and into Callon Merger Sub, with Callon Merger Sub "
        "surviving the merger.",
    )
    assert got is None


def test_a_merger_subs_description_does_not_swallow_the_next_name():
    """FairPoint 2017: the merger sub's description ends right before the parent's name."""
    got = N.definitions(
        "merger with Falcon Merger Sub, Inc. (“Merger Sub”), a Delaware corporation and "
        "wholly-owned subsidiary of Consolidated Communications Holdings, Inc., a Delaware "
        "corporation (“Consolidated”)"
    )
    assert got["consolidated"] == "Consolidated Communications Holdings, Inc."


def test_a_term_after_another_terms_description_is_the_named_parent():
    """NIC 2021: the description is Merger Sub's; Parent is Tyler Technologies."""
    got = N.definitions(
        "On April 21, 2021, Topos Acquisition, Inc. (“Merger Sub”), a Delaware corporation and "
        "wholly owned subsidiary of Tyler Technologies, Inc. (“Parent”)"
    )
    assert got["parent"] == "Tyler Technologies, Inc."
