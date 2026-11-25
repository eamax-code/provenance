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


def _pred(names, *paras, cik=MEDCO, own=("MEDCO HEALTH SOLUTIONS INC",), former=()):
    own = {N.norm(n) for n in (*own, *former)}
    return N.read_predecessor(list(paras), cik, own, names, ON)


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
        "In the holding company reorganization, the Company became a wholly owned subsidiary "
        "of Express Scripts Holding Company.",
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


def test_the_kind_comes_from_the_matched_sentence_not_the_whole_filing(db):
    """D-01b label fix: "successor issuer" and a defined "Holding Company Merger" elsewhere in an
    acquisition's 8-K do not make it a reorganisation (Limestone 2023, Palomar 2013)."""
    names = _companies(db)
    got = _pred(
        names,
        "The Company merged with and into Callon Petroleum Company (the “Holding Company "
        "Merger”), with Callon Petroleum Company surviving.",
        "Pursuant to Rule 12g-3(a), the surviving company is the successor issuer.",
    )
    assert (got["successor_cik"], got["kind"]) == (OTHER, "merged")
    got = _pred(
        names,
        "Express Scripts Holding Company is the successor issuer to Express Scripts, Inc. for "
        "its notes.",
        "Upon completion of the merger, the Company became a wholly owned subsidiary of Express "
        "Scripts Holding Company.",
    )
    assert (got["successor_cik"], got["kind"]) == (ESH, "acquired")


def test_a_successor_with_the_filers_own_name_succeeds_it(db):
    """BlackRock 2024: "Old BlackRock became a wholly owned subsidiary of New BlackRock", where New
    BlackRock carries the filer's former name: a reorganisation, though the sentence says not."""
    names = _companies(db)
    got = _pred(
        names,
        "By and among Medco Health Solutions, Inc. (formerly known as Express Scripts Holding "
        "Company), a Delaware corporation (“Old ESH”), and Express Scripts Holding Company, a "
        "Delaware corporation (“New ESH”). Old ESH became a wholly owned subsidiary of New ESH.",
        former=("EXPRESS SCRIPTS HOLDING CO",),
    )
    assert (got["successor_cik"], got["kind"]) == (ESH, "succeeded")
    # Chubb 2016: ACE later took the name Chubb; the filer's current name is not a former one
    got = _pred(names, "As a result of the Merger, the Company became a wholly owned subsidiary "
                "of Express Scripts Holding Company.",
                own=("EXPRESS SCRIPTS HOLDING CO",))  # fmt: skip
    assert got is None or got["kind"] == "acquired"
    # Motricity 2013: the transaction's own name; STERIS 2015: a successor-issuer sentence names
    # the same successor as the one the company became a subsidiary of
    got = _pred(names, "Upon completion of the Reorganization, the Company became a wholly owned "
                "subsidiary of Express Scripts Holding Company.")  # fmt: skip
    assert got["kind"] == "succeeded"
    got = _pred(names, "As a result of the Combination, the Company became a wholly owned "
                "subsidiary of Callon Petroleum Company.", "Callon Petroleum Company is the "
                "successor issuer to the Company pursuant to Rule 12g-3(a).")  # fmt: skip
    assert (got["successor_cik"], got["kind"]) == (OTHER, "succeeded")
    # NorthStar 2017: another party's defined "Redomestication Merger" in the same sentence
    got = _pred(
        names,
        "(i) NSAM merged into Colony (the “Redomestication Merger”), and (ii) the Company merged "
        "with and into Callon Petroleum Company, with Callon Petroleum Company surviving.",
    )
    assert (got["successor_cik"], got["kind"]) == (OTHER, "merged")


def test_old_subjects_and_a_second_sentence_mark_a_succession(db):
    """TWDC 2019: "Old Disney became a wholly owned subsidiary of Disney"; Motricity 2013: the
    Plan of Reorganization's sentence first, "Upon completion of the Reorganization" after it.
    Gannett 2019 ("the Company became a wholly owned subsidiary of" an acquirer that took its
    name at closing) stays an acquisition."""
    names = _companies(db)
    got = _pred(
        names,
        "Medco Health Solutions, Inc. (“Old Medco”) and Express Scripts Holding Company "
        "(“Express Scripts”) signed. Old Medco became a wholly owned subsidiary of Express "
        "Scripts.",
    )
    assert (got["successor_cik"], got["kind"]) == (ESH, "succeeded")
    got = _pred(
        names,
        "Pursuant to the Agreement and Plan of Reorganization, the Company became a wholly owned "
        "subsidiary of Express Scripts Holding Company.",
        "Upon completion of the Reorganization, the Company became a wholly owned subsidiary of "
        "Express Scripts Holding Company.",
    )
    assert (got["successor_cik"], got["kind"]) == (ESH, "succeeded")
    assert got["quote"].startswith("Upon completion of the Reorganization")
    got = _pred(
        names,
        "As a result of the Merger, a change of control of the Company occurred and the Company "
        "became a wholly owned subsidiary of Express Scripts Holding Company.",
        former=("EXPRESS SCRIPTS HOLDING CO",),
    )
    assert (got["successor_cik"], got["kind"]) == (ESH, "acquired")


def test_a_reviewed_override_sets_the_kind_after_the_rule(tmp_path):
    """United Financial 2014: the rule reads "Legacy United merged with and into the Company" as
    a succession; the reviewed file says merged. An override whose link changed is reported."""
    f = tmp_path / "reviewed.csv"
    f.write_text('predecessor_cik,successor_cik,kind,quote,reason\n'
                 f'{MEDCO},{ESH},merged,"Legacy merged into the Company.","a merger"\n'
                 f'{OTHER},{ESH},acquired,"gone","the link changed"\n')  # fmt: skip
    chosen = {MEDCO: {"successor_cik": ESH, "kind": "succeeded"}}
    unmatched = N.apply_overrides(chosen, N.reviewed_overrides(f))
    assert chosen[MEDCO]["kind"] == "merged" and unmatched == [(OTHER, ESH)]
    # the shipped file: every row a known kind, with a quote and a reason
    rows = list(N.reviewed_overrides().values())
    assert rows and all(r["kind"] in N.KINDS and r["quote"] and r["reason"] for r in rows)


def test_a_name_resolves_to_the_company_holding_it_on_the_date(db):
    """D-01e: "WestRock Company" in 2015 was today's WRKCo (it took that name in 2018); the
    holding company that took the name in 2018 is the match only after it did."""
    from app.db.models import CompanyAlias

    names = _companies(db)  # noqa: F841 (the fixture companies)
    now = datetime.now(UTC)
    old, new = "0000000961", "0000000962"
    for cik, name in ((old, "WRKCo Inc."), (new, "WestRock Co")):
        db.add(Company(cik=cik, legal_name=name, source_url="https://www.sec.gov/",
                       first_detected_at=now, last_processed_at=now,
                       quality_status="ok"))  # fmt: skip
    db.add(CompanyAlias(cik=old, alias="WestRock Co", kind="former", valid_to=date(2018, 11, 2)))
    db.add(CompanyAlias(cik=new, alias="WRK Holdco", kind="former", valid_to=date(2018, 3, 1)))
    db.commit()
    names = N.Names(db)
    assert names.find("WestRock Company", date(2015, 7, 2), exclude="x") == old
    assert names.find("WestRock Company", date(2019, 6, 1), exclude="x") == new
    # a lone current holder is kept whatever the date: EDGAR's former names include formatting
    # variants of one company's name, dated when EDGAR changed them ("LILLY ELI & CO")
    assert names.find("WRKCo Inc.", date(2015, 7, 2), exclude="x") == old


def test_coverage_plc_slash_and_former_holders(db):
    """D-01d: "STERIS plc" after a comma-less run is a name; a bare trailing slash on an EDGAR
    name goes ("WALT DISNEY CO/") but a state tag written without a space names another company
    ("PEOPLES BANCORP INC/NC"); with no current holder and two former ones, the one holding the
    name on the date (Gannett Co., Inc. in 2013: today's TEGNA, not the Gannett spun off in
    2015)."""
    from app.db.models import CompanyAlias

    assert N.tail_name("the Exchange Act), STERIS plc") == "STERIS plc"
    assert N.norm("WALT DISNEY CO/") == N.norm("The Walt Disney Company")
    assert N.norm("PEOPLES BANCORP INC/NC") != N.norm("PEOPLES BANCORP INC")
    now = datetime.now(UTC)
    tegna, spun = "0000000971", "0000000972"
    for cik, name in ((tegna, "TEGNA INC"), (spun, "Gannett Media Corp.")):
        db.add(Company(cik=cik, legal_name=name, source_url="https://www.sec.gov/",
                       first_detected_at=now, last_processed_at=now,
                       quality_status="ok"))  # fmt: skip
    for cik, alias, to in ((tegna, "GANNETT CO INC", date(2015, 6, 29)),
                           (spun, "New Gannett", date(2015, 6, 29)),
                           (spun, "GANNETT CO INC", date(2019, 11, 19))):  # fmt: skip
        db.add(CompanyAlias(cik=cik, alias=alias, kind="former", valid_to=to))
    db.commit()
    names = N.Names(db)
    assert names.find("Gannett Co., Inc.", date(2013, 12, 24), exclude="x") == tegna
    assert names.find("Gannett Co., Inc.", date(2016, 8, 9), exclude="x") == spun
