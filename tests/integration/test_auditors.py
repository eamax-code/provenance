"""E-3: audit firms from annual-report cover tags in the Financial Statement and Notes data sets."""

from __future__ import annotations

import zipfile
from datetime import date

from app.db.models import Filing, utcnow
from app.services import auditors

SUB = "adsh\tcik\tname\tform\tperiod\tfy\tfp\tfiled"
TXT = ("adsh\ttag\tversion\tddate\tqtrs\tiprx\tlang\tdcml\tdurp\tdatp\tdimh\tdimn\tcoreg\t"
       "escaped\tsrclen\ttxtlen\tfootnote\tfootlen\tcontext\tvalue")  # fmt: skip
A24, A25, Q = "0000320193-25-000001", "0000320193-26-000001", "0000320193-26-000002"


def _txt(adsh, tag, ddate, context, value, dimn="0", coreg=""):
    return "\t".join((adsh, tag, "dei/2025", ddate, "4", "0", "en-US", "32767", "0", "0",
                      "0x0", dimn, coreg, "0", "1", "1", "", "0", context, value))  # fmt: skip


def make_zip(tmp_path, name="2026_03_notes.zip"):
    sub = [SUB,
           "\t".join((A24, "320193", "APPLE INC", "10-K", "20241231", "2024", "FY", "20250301")),
           "\t".join((A25, "320193", "APPLE INC", "10-K", "20251231", "2025", "FY", "20260301")),
           "\t".join((Q, "320193", "APPLE INC", "10-Q", "20260331", "2026", "Q1", "20260501"))]
    txt = [TXT,
           _txt(A24, "AuditorName", "20241231", "c1", "Ernst & Young LLP"),
           _txt(A24, "AuditorFirmId", "20241231", "c1", "00042"),
           _txt(A24, "AuditorLocation", "20241231", "c1", "San Jose, California"),
           # the report after the change names both firms, each for the year it audited
           _txt(A25, "AuditorName", "20241231", "old", "Ernst & Young LLP"),
           _txt(A25, "AuditorFirmId", "20241231", "old", "42"),
           _txt(A25, "AuditorName", "20251231", "new", "KPMG LLP"),
           _txt(A25, "AuditorFirmId", "20251231", "new", "185"),
           _txt(A25, "AuditorLocation", "20251231", "new", "Santa Clara, California"),
           _txt(A25, "AuditorName", "20251231", "seg", "Other Firm", dimn="1"),  # a dimension
           _txt(A25, "AuditorName", "20251231", "co", "Sub Auditor", coreg="Sub"),  # coregistrant
           _txt(Q, "AuditorName", "20260331", "q", "Not An Annual Report"),
           _txt(A25, "TradingSymbol", "20251231", "c9", "aapl")]  # fmt: skip
    path = tmp_path / name
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("sub.tsv", "\n".join(sub) + "\n")
        z.writestr("txt.tsv", "\n".join(txt) + "\n")
    return path


def test_parse_pairs_tags_by_context_and_skips_dimensions_and_other_forms(tmp_path):
    rows, syms = auditors.parse_notes_zip(make_zip(tmp_path))
    by = {(r["accession_number"], r["pcaob_firm_id"]): r for r in rows}
    assert set(by) == {(A24, "42"), (A25, "42"), (A25, "185")}
    assert by[(A25, "185")]["auditor_location"] == "Santa Clara, California"
    assert by[(A25, "42")]["audited_through"] == date(2024, 12, 31)
    assert syms[0]["symbol"] == "AAPL" and syms[0]["accession_number"] == A25


def test_overview_block_current_history_changes_and_as_of(db, client, ingested_aapl, tmp_path):
    assert auditors.load(db, make_zip(tmp_path))["reports"] == 2
    assert auditors.load(db, make_zip(tmp_path))["auditor_rows"] == 3  # reload replaces
    db.add(Filing(cik="0000320193", accession_number="0000320193-25-000009", form_type="8-K",
                  filing_date=date(2025, 6, 2), items="4.01,9.01",
                  source_url="https://www.sec.gov/Archives/edgar/data/320193/x-index.html",
                  first_detected_at=utcnow(), quality_status="ok"))  # fmt: skip
    db.commit()
    b = auditors.for_company(db, "0000320193")
    assert b["current"]["name"] == "KPMG LLP" and b["current"]["pcaob_firm_id"] == "185"
    assert b["current"]["since_fiscal_year"] == 2025
    assert b["current"]["latest_report"]["source_url"].endswith(f"{A25}-index.html")
    assert [h["name"] for h in b["history"]] == ["KPMG LLP", "Ernst & Young LLP"]
    assert b["changes"][0]["item"] == "4.01" and b["changes"][0]["filing_date"] == "2025-06-02"
    before = auditors.for_company(db, "0000320193", as_of=date(2025, 12, 31))
    assert before["current"]["name"] == "Ernst & Young LLP"
    o = client.get("/v1/public/companies/320193/overview").json()
    assert o["auditor"]["current"]["name"] == "KPMG LLP"
    assert "auditor" in o["as_of_scope"]["point_in_time"]


def test_firm_ids_are_normalised():
    assert auditors.firm_id("00042") == "42" and auditors.firm_id(" ") is None
