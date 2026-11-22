"""E-1: institutional ownership from Form 13F data sets, joined through the internal CUSIP map."""

from __future__ import annotations

import zipfile
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import select

from app.db.models import Holding13F, IssuerCusip
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


def make_zip(folder: Path, name: str = "01jun2026-31aug2026_form13f.zip") -> Path:
    path = folder / name
    sub = [SUB] + ["\t".join((a, d, f, c, p)) for a, d, f, c, p, _, _ in FILINGS]
    cover = [COVER] + [
        "\t".join((a, p, "Y" if t else "", "1" if t else "", t, "", "", "", "", n,
                   "1 MAIN ST", "", "CITY", "NY", "10001",
                   "13F NOTICE" if f == "13F-NT" else "13F HOLDINGS REPORT"))
        for a, _, f, _, p, n, t in FILINGS
    ]  # fmt: skip
    summary = [SUMMARY] + ["\t".join((a, "0", "1", "1000", "N")) for a, *_ in FILINGS]
    info = [INFO] + [
        "\t".join((a, str(i), "ISSUER", t, c, "", str(v), str(s), k, pc, "SOLE", "", "0", "0", "0"))
        for i, (a, c, t, v, s, k, pc) in enumerate(ROWS)
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
    assert b["flows"] == {"new": 1, "added": 1, "reduced": 1, "exited": 1}
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
    assert b["flows"] == {"new": 1, "added": 1, "reduced": 0, "exited": 1}
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
                                                          "exited": 0}  # fmt: skip
        assert b["shares_held"] == 320 and any("holding company reorganisation" in n
                                               for n in b["notes"])  # fmt: skip
    # a merger counterpart (accounting predecessor) is never combined
    link = db.scalar(select(RegistrantSuccession))
    link.match_method = "accounting_predecessor"
    db.commit()
    assert thirteenf.reorganisation_aliases(db, old) == []
