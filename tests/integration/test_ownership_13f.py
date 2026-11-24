"""E-1: institutional ownership from Form 13F data sets, joined through the internal CUSIP map."""

from __future__ import annotations

import zipfile
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import select

from app.db.models import Filing13F, Holding13F, IssuerCusip
from app.services import cusips, thirteenf

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "connections"
AAPL, MSFT_CUSIP = "037833100", "594918104"
SUB = "ACCESSION_NUMBER\tFILING_DATE\tSUBMISSIONTYPE\tCIK\tPERIODOFREPORT"
COVER = (
    "ACCESSION_NUMBER\tREPORTCALENDARORQUARTER\tISAMENDMENT\tAMENDMENTNO\tAMENDMENTTYPE\t"
    "CONFDENIEDEXPIRED\tDATEDENIEDEXPIRED\tDATEREPORTED\tREASONFORNONCONFIDENTIALITY\t"
    "FILINGMANAGER_NAME\tFILINGMANAGER_STREET1\tFILINGMANAGER_STREET2\tFILINGMANAGER_CITY\t"
    "FILINGMANAGER_STATEORCOUNTRY\tFILINGMANAGER_ZIPCODE\tREPORTTYPE"
)
SUMMARY = "ACCESSION_NUMBER\tOTHERINCLUDEDMANAGERSCOUNT\tTABLEENTRYTOTAL\tTABLEVALUETOTAL\t" \
    "ISCONFIDENTIALOMITTED"  # fmt: skip
INFO = (
    "ACCESSION_NUMBER\tINFOTABLE_SK\tNAMEOFISSUER\tTITLEOFCLASS\tCUSIP\tFIGI\tVALUE\tSSHPRNAMT\t"
    "SSHPRNAMTTYPE\tPUTCALL\tINVESTMENTDISCRETION\tOTHERMANAGER\tVOTING_AUTH_SOLE\t"
    "VOTING_AUTH_SHARED\tVOTING_AUTH_NONE"
)
# (accession, filed, form, manager cik, period, name, amendment type)
FILINGS = [
    ("0000001001-26-000001", "10-MAY-2026", "13F-HR", "1001", "31-MAR-2026", "Alpha Capital", ""),
    ("0000001002-26-000001", "10-MAY-2026", "13F-HR", "1002", "31-MAR-2026", "Beta Advisors", ""),
    ("0000001004-26-000001", "10-MAY-2026", "13F-HR", "1004", "31-MAR-2026", "Delta LLC", ""),
    ("0000001005-26-000001", "10-MAY-2026", "13F-HR", "1005", "31-MAR-2026", "Echo Trust", ""),
    ("0000001001-26-000002", "01-AUG-2026", "13F-HR", "1001", "30-JUN-2026", "Alpha Capital", ""),
    ("0000001002-26-000002", "02-AUG-2026", "13F-HR", "1002", "30-JUN-2026", "Beta Advisors", ""),
    ("0000001002-26-000003", "20-AUG-2026", "13F-HR/A", "1002", "30-JUN-2026", "Beta Advisors",
     "RESTATEMENT"),
    ("0000001003-26-000001", "03-AUG-2026", "13F-HR", "1003", "30-JUN-2026", "Gamma Partners",
     ""),
    ("0000001003-26-000002", "25-AUG-2026", "13F-HR/A", "1003", "30-JUN-2026", "Gamma Partners",
     "NEW HOLDINGS"),
    ("0000001004-26-000002", "04-AUG-2026", "13F-HR", "1004", "30-JUN-2026", "Delta LLC", ""),
    ("0000001006-26-000001", "05-AUG-2026", "13F-NT", "1006", "30-JUN-2026", "Foxtrot", ""),
    ("0000001007-22-000001", "10-NOV-2022", "13F-HR", "1007", "30-SEP-2022", "Golf Old", ""),
]  # fmt: skip
# (accession, cusip, title, value, shares, type, put/call)
ROWS = [
    ("0000001001-26-000001", AAPL, "COM", 20000, 100, "SH", ""),
    ("0000001002-26-000001", AAPL, "COM", 40000, 200, "SH", ""),
    ("0000001004-26-000001", AAPL, "COM", 60000, 300, "SH", ""),
    ("0000001005-26-000001", AAPL, "COM", 8000, 40, "SH", ""),
    ("0000001001-26-000002", AAPL, "COM", 20000, 100, "SH", ""),
    ("0000001001-26-000002", AAPL, "COM", 10000, 50, "SH", ""),  # another discretion: summed
    ("0000001001-26-000002", AAPL, "COM", 99999, 1000, "SH", "Put"),  # an option: left out
    ("0000001001-26-000002", AAPL, "NOTE 2.5%", 5000, 5000, "PRN", ""),  # principal: left out
    ("0000001002-26-000002", AAPL, "COM", 40000, 200, "SH", ""),
    ("0000001002-26-000003", AAPL, "COM", 10000, 50, "SH", ""),
    ("0000001003-26-000001", AAPL, "COM", 14000, 70, "SH", ""),
    ("0000001003-26-000002", AAPL, "COM", 2000, 10, "SH", ""),
    ("0000001004-26-000002", MSFT_CUSIP, "COM", 9000, 30, "SH", ""),
    ("0000001007-22-000001", AAPL, "COM", 5, 30, "SH", ""),  # thousands before 2023
]


def make_zip(
    folder: Path,
    name: str = "01jun2026-31aug2026_form13f.zip",
    rows: list | None = None,
    names: dict | None = None,
) -> Path:
    path = folder / name
    sub = [SUB] + ["\t".join((a, d, f, c, p)) for a, d, f, c, p, _, _ in FILINGS]
    cover = [COVER] + [
        "\t".join((a, p, "Y" if t else "", "1" if t else "", t, "", "", "", "", n,
                   "1 MAIN ST", "", "CITY", "NY", "10001",
                   "13F NOTICE" if f == "13F-NT" else "13F HOLDINGS REPORT"))
        for a, _, f, _, p, n, t in FILINGS
    ]  # fmt: skip
    summary = [SUMMARY] + ["\t".join((a, "0", "1", "1000", "N")) for a, *_ in FILINGS]
    nm, tail = names or {}, ("SOLE", "", "0", "0", "0")
    info = [INFO] + [
        "\t".join(
            (a, str(i), nm.get((a, c), nm.get(c, "ISSUER")), t, c, "", str(v), str(s), k, pc) + tail
        )  # fmt: skip
        for i, (a, c, t, v, s, k, pc) in enumerate(ROWS if rows is None else rows)
    ]
    with zipfile.ZipFile(path, "w") as z:
        for fname, lines in (("SUBMISSION.tsv", sub), ("COVERPAGE.tsv", cover),
                             ("SUMMARYPAGE.tsv", summary), ("INFOTABLE.tsv", info)):  # fmt: skip
            z.writestr(fname, "\n".join(lines) + "\n")
    return path


@pytest.fixture
def loaded_13f(db, ingested_aapl, tmp_path):
    text = (FIXTURES / "schedule13g.xml").read_text()
    assert cusips.record_schedule(db, text, "0000000000-26-000001", date(2026, 2, 1)) == 1
    db.commit()
    return thirteenf.load_dataset(db, make_zip(tmp_path))


def test_cusip_rules():
    assert cusips.valid("037833100") and not cusips.valid("037833101")
    assert cusips.valid("30233Q108") and not cusips.valid("ABC")
    assert cusips.from_isin("US0378331005") == AAPL and cusips.from_isin("GB0002634946") is None
    assert cusips.is_share_class("CL A") and cusips.is_share_class("COM NEW")
    assert not cusips.is_share_class("PFD SER A") and not cusips.is_share_class("SPONSORED ADR")
    s = cusips.from_schedule((FIXTURES / "schedule13d.xml").read_text())
    assert s["issuer_cik"] == "0000939930" and s["cusips"] == ["74737V205"]
    assert s["class_title"].startswith("Common Stock")


def test_values_quarters_and_completeness():
    assert thirteenf.dollars(Decimal(5), date(2022, 11, 10)) == 5000
    assert thirteenf.dollars(Decimal(5), date(2023, 1, 3)) == 5
    assert thirteenf.quarter_ends(date(2026, 6, 30)) == date(2026, 6, 30)
    assert thirteenf.quarter_ends(date(2026, 2, 3)) == date(2025, 12, 31)
    # Q3 2026's deadline (Nov 14) has passed but the loaded data stops at Aug 31
    assert thirteenf.complete_quarter(date(2026, 11, 22), date(2026, 8, 31)) == date(2026, 6, 30)
    assert thirteenf.complete_quarter(date(2026, 8, 1), date(2026, 8, 31)) == date(2026, 3, 31)
    assert thirteenf.complete_quarter(date(2026, 11, 22), None) is None
    assert thirteenf.window_end("x/01jun2026-31aug2026_form13f.zip") == date(2026, 8, 31)


def test_load_sums_rows_and_skips_options_principal_and_notices(db, loaded_13f, tmp_path):
    assert loaded_13f["filings"] == len(FILINGS) and loaded_13f["window_end"] == "2026-08-31"
    alpha = db.scalar(select(Holding13F).where(Holding13F.accession_number
                                               == "0000001001-26-000002"))  # fmt: skip
    assert alpha.shares == 150 and alpha.value_usd == 30000
    old = db.scalar(select(Holding13F).where(Holding13F.filer_cik == "0000001007"))
    assert old.value_usd == 5000  # thousands, filed before 2023-01-03
    again = thirteenf.load_dataset(db, make_zip(tmp_path))  # reloading replaces each filing
    assert again["holdings"] == loaded_13f["holdings"]
    assert db.query(Holding13F).count() == loaded_13f["holdings"]


def test_ownership_api_amendments_flows_and_holders(client, auth, loaded_13f):
    r = client.get("/v1/companies/320193/ownership", headers=auth)
    assert r.status_code == 200, r.text
    b = r.json()
    assert (b["quarter"], b["previous_quarter"]) == ("2026-06-30", "2026-03-31")
    assert b["filed_through"] == "2026-08-25" and "45 days" in b["lag_note"]
    # Alpha 150, Beta restated to 50, Gamma 70 + 10 new holdings; Delta exited; Echo not filed
    assert b["holders_count"] == 3 and b["holders_count_change"] == -1
    # Echo held it last quarter and has filed nothing for this one: not an exit, but not a holder
    assert b["flows"] == {"new": 1, "added": 1, "reduced": 1, "exited": 1, "not_filed": 1}
    f = b["flows"]
    assert b["holders_count_change"] == f["new"] - f["exited"] - f["not_filed"]
    assert b["shares_held"] == 280 and b["value_usd"] == 56000
    so = b["shares_outstanding"]["value"]
    assert b["institutional_pct"] == round(280 / so * 100, 1)
    assert b["institutional_pct_derived"]["formula"].startswith("13F shares held")
    names = [h["name"] for h in b["data"]]
    assert names == ["Alpha Capital", "Gamma Partners", "Beta Advisors"]
    alpha, gamma, beta = b["data"]
    assert alpha["change"] == "added" and alpha["shares_change"] == 50
    assert alpha["shares_change_pct"] == 50.0 and alpha["filer_cik"] == "0000001001"
    assert gamma["change"] == "new" and gamma["shares"] == 80
    assert beta["change"] == "reduced" and beta["accession_number"] == "0000001002-26-000003"
    assert beta["filing_url"].startswith("https://www.sec.gov/Archives/edgar/data/1002/")
    assert "cusip" not in r.text.lower() and AAPL not in r.text


def test_ownership_point_in_time(client, auth, loaded_13f):
    """Before Beta's restatement and Gamma's added holdings were filed."""
    b = client.get("/v1/companies/320193/ownership?as_of=2026-08-15", headers=auth).json()
    assert b["quarter"] == "2026-06-30" and b["filed_through"] == "2026-08-04"
    assert b["shares_held"] == 150 + 200 + 70
    assert b["flows"] == {"new": 1, "added": 1, "reduced": 0, "exited": 1, "not_filed": 1}
    early = client.get("/v1/companies/320193/ownership?as_of=2026-08-01", headers=auth).json()
    assert early["quarter"] == "2026-03-31" and early["holders_count"] == 4


def test_ownership_paging_demo_cap_and_missing(client, auth, loaded_13f, db):
    page = client.get("/v1/companies/320193/ownership?limit=1&offset=1", headers=auth).json()
    assert [h["name"] for h in page["data"]] == ["Gamma Partners"] and page["meta"]["has_more"]
    db.query(IssuerCusip).delete()
    db.commit()
    r = client.get("/v1/companies/320193/ownership", headers=auth)
    assert r.status_code == 404 and r.json()["error"]["code"] == "no_ownership_data"


def test_overview_has_the_ownership_block(client, loaded_13f):
    o = client.get("/v1/public/companies/320193/overview").json()
    assert "ownership" in o["as_of_scope"]["point_in_time"]
    own = o["ownership"]
    assert own["quarter"] == "2026-06-30" and len(own["top_holders"]) == 3
    assert "cusip" not in str(o).lower()


def test_prefix_rule_maps_other_share_classes_only(db, loaded_13f):
    n = cusips.map_prefixes(db, {"037833209": "CL B", "037833308": "PFD SER A"})
    assert n == 1
    row = db.get(IssuerCusip, "037833209")
    assert row.cik == "0000320193" and row.method == "issuer_prefix"
    assert db.get(IssuerCusip, "037833308") is None


def test_a_13f_name_saying_preferred_warrant_or_depositary_is_never_a_share_class():
    for name in ("STIFEL FINL CORP DEP", "BANK OF AMERICA CORP PFD", "ENDRA LIFE SCIENCES INC WT",
                 "MOVANO INCORPORATED WARRANT EXP 013128", "EOS ENERGY RIGHT EXP 072126",
                 "KIMCO REALTY CORP DEP SHS REP", "ACME UNITS", "ACME 5.5% NOTES",
                 "AROGO CAP -CW23 EQUITY", "DATA KNIGH-CW28", "TRADEUP ACQUI-CW EQUITY",
                 "NEW PROVIDENCE ACQ A CW28", "CODERE ONLINE LUXEMBOU CW"):  # fmt: skip
        assert cusips.names_other_security(name), name
    # whole words only: these are ordinary issuer names
    for name in ("UNITEDHEALTH GROUP INC", "UNITED RENTALS INC", "NOTEWORTHY AI INC",
                 "HOME DEPOT INC", "DEPOMED INC", "WTW PLC", "RIGHTSIDE GROUP", None,
                 "LEARN CW INVESTMENT COR", "CW ETF TRUST", "CW", "CWBR INC"):  # fmt: skip
        assert not cusips.names_other_security(name), name


def test_a_preferred_line_titled_common_does_not_extend_the_prefix(db, ingested_aapl, tmp_path):
    rows = [("0000001001-26-000002", "037833407", "COM", 100, 4, "SH", ""),
            ("0000001001-26-000002", "037833506", "COM", 100, 4, "SH", "")]  # fmt: skip
    path = make_zip(tmp_path, rows=rows, names={"037833407": "APPLE INC DEP SH PFD SER A"})
    ds = thirteenf.parse_dataset(path)
    list(ds.holdings)
    assert set(ds.classes) == {"037833506"}  # the preferred line is held but not a class


def test_a_cusip_is_judged_on_all_its_lines_at_the_15_percent_share(db, ingested_aapl, tmp_path):
    acc = "0000001001-26-000002"
    pfd, ok = "037833407", "037833506"
    rows = [(acc, pfd, "Common Stock", 25, 1, "SH", "")] + [(acc, ok, "COM", 100, 4, "SH", "")]
    rows += [(f"0000001002-26-00000{i}", pfd, "Common Stock", 25, 1, "SH", "") for i in (2, 3)]
    rows += [(f"0000001004-26-00000{i}", ok, "COM", 100, 4, "SH", "") for i in (2,)]
    # the first line names the preferred as the plain company (it alone once made it a class);
    # the other two say PFD
    names = {(acc, pfd): "CITIZENS FINL GROUP", pfd: "CITIZENS FINL 6.5 PFD SER I"}
    path = make_zip(tmp_path, rows=rows, names=names)
    ds = thirteenf.parse_dataset(path)
    list(ds.holdings)
    assert set(ds.classes) == {ok}
    assert cusips.other_security(6, 1) and not cusips.other_security(7, 1)  # 15%: 1 of 6, not 7
    assert cusips.line_names_other_security("CFG 6 1/2 PERP", "PUBLIC")
    assert cusips.line_names_other_security("DTE ENERGY CO", "PREFERRED STOCK")
    assert cusips.line_names_other_security("ACME ACQUISITION CORP UNIT", "COM")
    assert not cusips.line_names_other_security("FERRELLGAS PARTNERS LP UNIT LT", "COM")
    assert not cusips.line_names_other_security("GRANITE REAL ESTATE INVT TR UNIT", "REIT")
    assert not cusips.line_names_other_security("APPLE INC", "COM")


def test_value_per_share_holds_out_a_prefix_link_far_below_the_common(db, loaded_13f):
    from app.db.models import Holding13F

    def lines(cusip, n, value):
        for i in range(n):
            db.add(Holding13F(accession_number=f"0000009{i:03d}-26-000001", cusip=cusip,
                              filer_cik=f"9{i:03d}", report_period=date(2026, 6, 30),
                              filing_date=date(2026, 8, 1), title_of_class="COM",
                              shares=Decimal(1000), value_usd=Decimal(value)))  # fmt: skip
        db.flush()

    lines("037833407", 3, 260)  # $0.26 a share against about $200 for the 13D/G common
    lines("037833506", 2, 260)  # too few lines that quarter: not judged
    low = cusips.value_outliers(db, {"037833407": "0000320193", "037833506": "0000320193"})
    assert set(low) == {"037833407"} and low["037833407"]["lines"] == 3
    assert low["037833407"]["reference_median"] == 200
    # no other mapped common of the company: not judged
    assert cusips.value_outliers(db, {"037833407": "0000789019"}) == {}
    assert cusips.map_prefixes(db, {"037833407": "COM", "037833506": "CL C"}) == 1
    assert db.get(IssuerCusip, "037833407") is None and db.get(IssuerCusip, "037833506")


def test_reviewed_removals_delete_only_the_listed_links(db, ingested_aapl, tmp_path):
    for c in ("037833407", "037833506"):
        cusips.record(db, "0000320193", c, "issuer_prefix", "COM")
    cusips.record(db, "0000320193", AAPL, "schedule_13dg", "Common Stock")
    listed = tmp_path / "reviewed.csv"
    cusips.record(db, "0000320193", "037833AB6", "issuer_prefix", "CLASS A")  # a 0% note
    listed = tmp_path / "reviewed.csv"
    listed.write_text(
        "cik,company,issuer_name_13f,title_of_class_13f,rule,links,reason,checked\n"
        "320193,Apple Inc.,Apple  Inc dep sh pfd,COM,issuer_name,1,preferred,2026-11-22\n"
        "320193,Apple Inc.,APPLE INC,CLASS A,debt_issue_number,1,note,2026-11-22\n"
    )
    reviewed = cusips.reviewed_removals(listed)
    names = {"037833407": {"APPLE INC DEP SH PFD"}, "037833506": {"APPLE INC"},
             AAPL: {"APPLE INC DEP SH PFD"}, "037833AB6": {"APPLE INC"}}  # fmt: skip
    gone = cusips.remove_reviewed(db, names, reviewed)
    assert sorted(gone) == [("0000320193", "APPLE INC", "debt_issue_number"),
                            ("0000320193", "APPLE INC DEP SH PFD", "issuer_name")]  # fmt: skip
    assert db.get(IssuerCusip, "037833407") is None and db.get(IssuerCusip, "037833AB6") is None
    # the debt row never reaches a share class of the same name; the 13D/G CUSIP is untouched
    assert db.get(IssuerCusip, "037833506") and db.get(IssuerCusip, AAPL)


def test_a_letter_in_the_issue_number_is_debt_and_never_a_share_class(db, loaded_13f):
    assert cusips.debt_issue_number("037833AB6") and not cusips.debt_issue_number(AAPL)
    assert cusips.map_prefixes(db, {"037833AB6": "CLASS A", "037833506": "CL C"}) == 1
    assert db.get(IssuerCusip, "037833AB6") is None and db.get(IssuerCusip, "037833506")


def test_the_reviewed_removal_list_names_no_cusip():
    text = cusips.REVIEWED_REMOVALS.read_text()
    reviewed = cusips.reviewed_removals()
    assert len(reviewed) == 128 and sum(reviewed.values()) == 132
    assert not any(cusips.valid(w) for w in text.replace(",", " ").split())


def test_stronger_source_wins_and_mcp_lists_the_tool(db, client, loaded_13f):
    assert not cusips.record(db, "0000789019", AAPL, "issuer_prefix")  # weaker: refused
    assert cusips.record(db, "0000789019", AAPL, "schedule_13dg", filing_date=date(2026, 9, 1))
    db.rollback()
    from app.api.routes_mcp import TOOLS

    assert TOOLS["institutional_ownership"]["path"] == "/v1/companies/{cik}/ownership"


def test_coverage_lists_13f_with_basis(db, settings, loaded_13f):
    from app.services import coverage

    row = coverage.thirteenf_row(db)
    assert row["label"] == "Institutional holdings (13F)" and row["filings"] == 11
    assert "2022-09-30 to 2026-06-30" in row["basis"] and "45 days" in row["basis"]
    assert any(f["label"] == row["label"] for f in coverage.compute(db, settings)["forms"])


def test_reorganisation_counts_both_cusips_as_one_class(db, ingested_aapl):
    """K-05 + E-1: after a holding company reorganisation (1:1), managers report the same shares
    under the old or the new CUSIP; the quarter counts each once and nobody falsely exits."""
    from app.db.models import Company, Filing13F, RegistrantSuccession, utcnow

    old, new, new_cusip = "0000320193", "0009999991", "037833209"
    db.add(Company(cik=new, legal_name="Apple Holdings, Inc.", source_url="https://www.sec.gov/",
                   first_detected_at=utcnow(), quality_status="ok"))  # fmt: skip
    cusips.record(db, old, AAPL, "schedule_13dg", filing_date=date(2026, 1, 1))
    cusips.record(db, new, new_cusip, "schedule_13dg", filing_date=date(2026, 7, 2))
    thirteenf.mark_loaded_through(db, date(2026, 8, 31))
    rows = [  # (manager, period, filed, cusip, shares)
        ("0000001001", date(2026, 3, 31), date(2026, 5, 10), AAPL, 100),
        ("0000001002", date(2026, 3, 31), date(2026, 5, 10), AAPL, 200),
        ("0000001001", date(2026, 6, 30), date(2026, 8, 1), AAPL, 120),  # still the old CUSIP
        ("0000001002", date(2026, 6, 30), date(2026, 8, 2), new_cusip, 200),  # already the new
    ]
    for i, (filer, period, filed, cusip, shares) in enumerate(rows):
        acc = f"{filer}-26-{i:06d}"
        db.add(Filing13F(accession_number=acc, filer_cik=filer, filer_name=f"Manager {filer[-1]}",
                         report_period=period, filing_date=filed, form_type="13F-HR",
                         source="test", created_at=utcnow()))  # fmt: skip
        db.add(Holding13F(accession_number=acc, cusip=cusip, filer_cik=filer,
                          report_period=period, filing_date=filed, title_of_class="COM",
                          shares=Decimal(shares), value_usd=Decimal(shares * 200)))  # fmt: skip
    db.commit()
    alone = thirteenf.ownership(db, old, today=date(2026, 11, 22))
    assert alone["flows"]["exited"] == 1  # without the link, manager 2 looks like an exit
    reorg = "holding_company_reorganization"
    db.add(RegistrantSuccession(predecessor_cik=old, successor_cik=new,
                                effective_date=date(2026, 7, 1), evidence_accession="x",
                                evidence_form="8-K12B", match_method=reorg,
                                confidence="high", updated_at=utcnow()))  # fmt: skip
    db.commit()
    for cik in (old, new):  # both pages
        company = db.get(Company, db.scalar(select(Company.id).where(Company.cik == cik)))
        b = thirteenf.for_company(db, company, today=date(2026, 11, 22))
        assert b["holders_count"] == 2 and b["flows"] == {"new": 0, "added": 1, "reduced": 0,
                                                          "exited": 0, "not_filed": 0}  # fmt: skip
        assert b["shares_held"] == 320 and any("holding company reorganisation" in n
                                               for n in b["notes"])  # fmt: skip
        assert b["flows_note"].startswith("This quarter spans the change of share identifier "
                                          "on 1 Jul 2026 (8-K12B)")  # fmt: skip
        assert "cusip" not in str(b).lower()  # the word never appears, nor any value
    # a merger counterpart (accounting predecessor) is never combined
    link = db.scalar(select(RegistrantSuccession))
    link.match_method = "accounting_predecessor"
    db.commit()
    assert thirteenf.reorganisation_aliases(db, old) == []


def test_flows_note_only_near_the_change():
    change = [(date(2026, 7, 1), "8-K12B")]
    assert thirteenf.flows_note(date(2026, 6, 30), change)  # reported after the change
    assert thirteenf.flows_note(date(2026, 9, 30), change)  # the quarter that contains it
    assert thirteenf.flows_note(date(2026, 12, 31), change) is None
    assert thirteenf.flows_note(date(2026, 3, 31), change) is None


def test_13f_issuer_name_rule_maps_unique_exact_names_only(db, ingested_aapl):
    """E-1c (b): a CUSIP whose dominant 13F issuer name equals the company's name, uniquely, with
    enough managers, as a share class, on an issuer number nobody else owns."""
    from app.db.models import Company, utcnow

    db.add(Company(cik="0000019617", legal_name="JPMORGAN CHASE & CO",
                   source_url="https://www.sec.gov/", first_detected_at=utcnow(),
                   quality_status="ok"))  # fmt: skip
    db.add(Company(cik="0001067983", legal_name="BERKSHIRE HATHAWAY INC",
                   source_url="https://www.sec.gov/", first_detected_at=utcnow(),
                   quality_status="ok"))  # fmt: skip
    db.commit()
    key = cusips.name_key
    assert key("BERKSHIRE HATHAWAY INC DEL") == key("Berkshire Hathaway Inc")
    names = {
        "46625H100": {"name": "JPMORGAN CHASE & CO", "share": 0.9, "filers": 5000, "title": "COM"},
        "084670702": {"name": "BERKSHIRE HATHAWAY INC DEL", "share": 0.8, "filers": 5400,
                      "title": "CL B NEW"},
        "084670108": {"name": "BERKSHIRE HATHAWAY INC DEL", "share": 0.8, "filers": 1600,
                      "title": "CL A"},
        "999999995": {"name": "JPMORGAN CHASE & CO", "share": 0.9, "filers": 5,  # too few
                      "title": "COM"},
        "037833308": {"name": "APPLE INC", "share": 0.9, "filers": 900,  # Apple's issuer number
                      "title": "PFD"},  # but not a share class
    }  # fmt: skip
    stored = {(c, cu) for c, cu, _ in cusips.map_by_13f_names(db, names)}
    assert stored == {("0000019617", "46625H100"), ("0001067983", "084670702"),
                      ("0001067983", "084670108")}  # fmt: skip
    assert db.get(IssuerCusip, "46625H100").method == "13f_issuer_name"


def test_name_rule_takes_adrs_partnership_units_and_exact_short_names(db, ingested_aapl):
    """Items 4 and 5 and BGC: ADRs, a partnership's units, and a key under four characters only
    on the exact legal name of exactly one company."""
    from app.db.models import Company, utcnow

    for cik, legal in (("0001114448", "NOVARTIS AG"), ("0001552000", "MPLX LP"),
                       ("0001094831", "BGC Group, Inc."), ("0001999001", "ACME ACQUISITION CORP"),
                       ("0001999002", "SPROTT PHYSICAL COPPER TRUST")):  # fmt: skip
        db.add(Company(cik=cik, legal_name=legal, source_url="https://www.sec.gov/",
                       first_detected_at=utcnow(), quality_status="ok"))  # fmt: skip
    db.commit()

    def cu(first8):
        return first8 + str(cusips.check_digit(first8))

    def line(name, title):
        return {"name": name, "share": 0.9, "filers": 400, "title": title}

    names = {
        cu("66987V10"): line("NOVARTIS AG SPONSORED ADR", "SPONSORED ADR"),
        cu("55336V10"): line("MPLX LP", "COM UNIT REP LTD"),
        cu("08892910"): line("BGC GROUP INC", "CL A"),
        cu("08892920"): line("BGC GROUP", "CL B"),  # not the exact legal name
        cu("00499910"): line("ACME ACQUISITION CORP", "UNIT 99/99/9999"),  # a SPAC unit
        cu("85207H10"): line("SPROTT PHYSICAL COPPER TRUST", "UNIT"),  # a trust's units
        cu("66987V20"): line("NOVARTIS AG SPON ADR PFD", "SPON ADR PFD"),  # never a preferred
    }
    stored = {(c, n) for c, _, n in cusips.map_by_13f_names(db, names)}
    assert stored == {("0001114448", "NOVARTIS AG SPONSORED ADR"), ("0001552000", "MPLX LP"),
                      ("0001094831", "BGC GROUP INC")}  # fmt: skip
    assert cusips.is_adr_title("SPONSORED ADS") and not cusips.is_adr_title("SPON ADR PFD")
    assert cusips.is_unit_title("UT LTD PTN INT") and not cusips.is_unit_title("UNIT 1 CL A 1/2 WT")


def test_latest_quarter_ownership_is_cached_until_the_data_changes(db, loaded_13f):
    """The cached block is the data's: a 13F load (the holdings version) or a link change makes
    a new one; as_of is never cached; the route may change what it gets without harm."""
    so = {"value": 15_000_000_000, "as_of_date": "2026-07-15", "source_url": "https://x"}
    first = thirteenf.ownership(db, "0000320193", shares_outstanding=so)
    first.pop("top_holders")  # a caller changing its copy never reaches the cache
    again = thirteenf.ownership(db, "0000320193", shares_outstanding=so)
    assert again["top_holders"] and again["quarter"] == first["quarter"]
    assert len(thirteenf._cache) == 1
    held = again["holders_count"]
    from app.db.models import Holding13F

    q = date.fromisoformat(again["quarter"])
    db.add(Holding13F(accession_number="0000009999-26-000001", cusip=AAPL, filer_cik="9999",
                      report_period=q, filing_date=date(2026, 8, 2), title_of_class="COM",
                      shares=Decimal(10), value_usd=Decimal(2000)))  # fmt: skip
    db.add(Filing13F(accession_number="0000009999-26-000001", filer_cik="9999",
                     filer_name="Zulu Capital", report_period=q, filing_date=date(2026, 8, 2),
                     form_type="13F-HR", source="test"))  # fmt: skip
    db.flush()
    stale = thirteenf.ownership(db, "0000320193", shares_outstanding=so)
    assert stale["holders_count"] == held  # same version: the cached block
    thirteenf.bump_holdings_version(db)
    db.flush()
    fresh = thirteenf.ownership(db, "0000320193", shares_outstanding=so)
    assert fresh["holders_count"] == held + 1
    # a link change is part of the key: a new class makes a new block
    cusips.record(db, "0000320193", "037833506", "issuer_prefix", "CL C")
    db.flush()
    assert [c["title"] for c in thirteenf.ownership(db, "0000320193", shares_outstanding=so)
            ["classes"]] != [c["title"] for c in fresh["classes"]]  # fmt: skip
    before = len(thirteenf._cache)
    thirteenf.ownership(db, "0000320193", as_of=date(2026, 9, 1), shares_outstanding=so)
    assert len(thirteenf._cache) == before  # as_of: never cached


def test_class_labels_are_plain_and_fall_back_to_the_title_as_filed():
    label = thirteenf.class_label
    assert label("COM UNIT REP LTD") == label("UNIT LTD PARTNER") == "Common units"
    assert label("SPONSORED ADR") == label("SPON ADS RP CL B") == "American depositary shares"
    assert label("COM CL A") == "Class A common stock"
    assert label("CLASS B") == "Class B common stock"
    assert label("COM NEW") == label("Common Stock, $0.00001 par value") == "Common stock"
    assert label("ORD SHS") == label("SHS") == "Ordinary shares"
    assert label(None) is None
    # Q-02 (25 Nov): capital stock and ordinary share classes, preferred, beneficial interest,
    # depositary receipts, and an issuer's name followed by COM
    assert label("CAP STK CL A") == "Class A capital stock"
    assert label("SHS CL A") == "Class A ordinary shares"
    assert label("PFD") == "Preferred stock"
    assert label("SH BEN INT") == label("COMMON SHARES OF BENEFICIAL") == (
        "Shares of beneficial interest")  # fmt: skip
    assert label("DEPOSITORY RCPT") == "Depositary receipts"
    assert label("LANDSTAR SYS INC COM") == "Common stock"
    assert label("ST STR P400MID") == "ST STR P400MID"  # not clean: as filed


def test_ownership_of_an_adr_class_gives_no_percentages(db, loaded_13f):
    so = {"value": 15_000_000_000, "as_of_date": "2026-07-15", "source_url": "https://x"}
    plain = thirteenf.ownership(db, "0000320193", shares_outstanding=so)
    assert plain["institutional_pct"] is not None
    assert plain["classes"] == [{"title": "Common Stock", "class_label": "Common stock",
                                 "held_as": "shares", "ratio": 1}]  # fmt: skip
    db.get(IssuerCusip, AAPL).class_title = "SPONSORED ADS"
    db.flush()
    adr = thirteenf.ownership(db, "0000320193", shares_outstanding=so)
    adr_class = {"title": "SPONSORED ADS", "class_label": "American depositary shares",
                 "held_as": "adr", "ratio": None}  # fmt: skip
    assert adr["classes"] == [adr_class]
    assert adr["institutional_pct"] is None and adr["institutional_pct_derived"] is None
    assert adr["shares_outstanding"] is None
    assert all(h["pct_of_outstanding"] is None for h in adr["top_holders"])
    assert thirteenf.ADR_NOTE in adr["notes"]


SUBMISSION = """<SEC-DOCUMENT>
<DOCUMENT>
<TYPE>13F-HR
<TEXT>
<XML>
<edgarSubmission xmlns="http://www.sec.gov/edgar/thirteenffiler">
 <formData><coverPage><reportCalendarOrQuarter>09-30-2026</reportCalendarOrQuarter>
  <filingManager><name>Alpha Capital</name></filingManager>
  <reportType>13F HOLDINGS REPORT</reportType></coverPage>
  <summaryPage><tableEntryTotal>3</tableEntryTotal><tableValueTotal>50000</tableValueTotal>
  </summaryPage></formData>
 <headerData><filerInfo><periodOfReport>09-30-2026</periodOfReport></filerInfo></headerData>
</edgarSubmission>
</XML>
</TEXT>
</DOCUMENT>
<DOCUMENT>
<TYPE>INFORMATION TABLE
<TEXT>
<XML>
<informationTable xmlns="http://www.sec.gov/edgar/document/thirteenf/informationtable">
 <infoTable><nameOfIssuer>APPLE INC</nameOfIssuer><titleOfClass>COM</titleOfClass>
  <cusip>037833100</cusip><value>40000</value>
  <shrsOrPrnAmt><sshPrnamt>200</sshPrnamt><sshPrnamtType>SH</sshPrnamtType></shrsOrPrnAmt>
 </infoTable>
 <infoTable><nameOfIssuer>APPLE INC</nameOfIssuer><titleOfClass>COM</titleOfClass>
  <cusip>037833100</cusip><value>9000</value><putCall>Put</putCall>
  <shrsOrPrnAmt><sshPrnamt>50</sshPrnamt><sshPrnamtType>SH</sshPrnamtType></shrsOrPrnAmt>
 </infoTable>
 <infoTable><nameOfIssuer>APPLE INC</nameOfIssuer><titleOfClass>COM</titleOfClass>
  <cusip>037833100</cusip><value>10000</value>
  <shrsOrPrnAmt><sshPrnamt>50</sshPrnamt><sshPrnamtType>SH</sshPrnamtType></shrsOrPrnAmt>
 </infoTable>
</informationTable>
</XML>
</TEXT>
</DOCUMENT>
</SEC-DOCUMENT>"""


def test_edgar_13f_submission_is_read_like_the_data_sets():
    from app.services import thirteenf_edgar

    idx = ("Form Type   Company Name   CIK   Date Filed  File Name\n"
           "13F-HR           ALPHA CAPITAL                       1001        2026-11-10  "
           "edgar/data/1001/0000001001-26-000099.txt\n"
           "13F-HR           OLDER                               1002        2026-08-20  "
           "edgar/data/1002/0000001002-26-000001.txt\n"
           "10-K             SOMEONE                             1003        2026-11-10  "
           "edgar/data/1003/0000001003-26-000001.txt\n")  # fmt: skip
    items = thirteenf_edgar.list_filings(idx, after=date(2026, 8, 31))
    assert [i["accession"] for i in items] == ["0000001001-26-000099"]  # after the data sets
    filing, rows = thirteenf_edgar.parse_submission(SUBMISSION, items[0])
    assert filing["report_period"] == date(2026, 9, 30) and filing["filer_name"] == "Alpha Capital"
    assert filing["entry_total"] == 3 and filing["source"] == "sec:13f-edgar"
    assert len(rows) == 1 and rows[0]["shares"] == 250 and rows[0]["value_usd"] == 50000  # no put


def test_13f_abbreviations_and_the_same_name_tie_break_rules():
    """STATE STR CORP is State Street; a same-name tie goes to the one active listed company only
    when the 13F line's legal form agrees (MEDTRONIC INC is not Medtronic plc), and a 13F name
    with no legal form never breaks a tie (FARMERS & MERCHANTS BANCORP)."""
    from app.services import cusips

    assert cusips.name_key_13f("STATE STR CORP") == cusips.name_key_13f("State Street Corp")
    assert cusips.name_key_13f("AMERIPRISE FINL INC") == cusips.name_key_13f(
        "Ameriprise Financial, Inc."
    )
    assert cusips.name_key_13f("ACME TR INC") != cusips.name_key_13f(
        "Acme Trust Inc"
    )  # TR not expanded
    assert (
        cusips.legal_form("MEDTRONIC INC") == "INC" and cusips.legal_form("Medtronic plc") == "PLC"
    )
    assert cusips.legal_form("LAZARD LTD") == "LTD" and cusips.legal_form("Lazard, Inc.") == "INC"
    assert cusips.legal_form("WATERSTONE FINL INC MD") == "INC"
    assert cusips.legal_form("FARMERS & MERCHANTS BANCORP") is None


def test_no_listed_shares_is_said_only_without_any_listing():
    """Tampa Electric (debt only) has no 13F holders because it has no listed stock; a listed
    company we failed to match must never read that way."""
    from app.db.models import Company
    from app.services.company_overview import _no_listed_shares

    debt_only = Company(cik="0000096271", legal_name="TAMPA ELECTRIC CO", ticker=None,
                        tickers="[]", exchanges="[]")  # fmt: skip
    assert _no_listed_shares(debt_only) == {
        "listed": False,
        "note": "No listed common stock, so no Form 13F holders.",
    }
    listed = Company(cik="0000093751", legal_name="STATE STREET CORP", ticker="STT",
                     tickers='["STT"]', exchanges='["NYSE"]')  # fmt: skip
    assert _no_listed_shares(listed) is None
    notes_only = Company(cik="0000068622", legal_name="QWEST CORP", ticker=None,
                         tickers='["CTBB"]', exchanges='["NYSE"]')  # fmt: skip
    assert _no_listed_shares(notes_only) is None  # a listing exists: not claimed as none


def test_concurrent_misses_compute_the_block_once(db, loaded_13f, monkeypatch):
    import threading
    import time

    from app.db.session import session_factory

    db.commit()
    thirteenf.clear_cache()
    calls, real = [], thirteenf._ownership

    def slow(*args, **kwargs):
        calls.append(1)
        time.sleep(0.3)  # long enough for every other request to arrive
        return real(*args, **kwargs)

    monkeypatch.setattr(thirteenf, "_ownership", slow)
    so = {"value": 15_000_000_000, "as_of_date": "2026-07-15", "source_url": "https://x"}
    start, counts = threading.Barrier(6), []

    def request():
        s = session_factory()()
        try:
            start.wait()
            counts.append(
                thirteenf.ownership(s, "0000320193", shares_outstanding=so)["holders_count"]
            )
        finally:
            s.close()

    threads = [threading.Thread(target=request) for _ in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(10)
    assert len(counts) == 6 and len(set(counts)) == 1
    assert len(calls) == 1  # one computed, five waited and read the cache
