"""D-13: SEC comment letters (docs/contracts/comment-letters.md)."""

from __future__ import annotations

import json
import zlib
from datetime import date

from app.db.models import CommentLetter, Filing, utcnow
from app.services import comment_letters as CL

CIK = "0000320193"
SEC_LETTER = (
    "United States securities and exchange commission March 6, 2024 Luca Maestri Chief "
    "Financial Officer Apple Inc. Re: Apple Inc. Form 10-K for the fiscal year ended "
    "September 30, 2023 File No. 001-36743 Dear Luca Maestri: We have reviewed your "
    "filing. Please tell us how your reportable segments meet ASC 280 and how you "
    "present non-GAAP measures under Item 10(e). We remind you that the company and its "
    "management are responsible for the accuracy and adequacy of their disclosures, "
    "notwithstanding any review, comments, action or absence of action by the staff."
)
CLOSING = (
    "May 16, 2024 Re: Apple Inc. Form 10-K Response dated March 20, 2024 File No. "
    "001-36743 Dear Luca Maestri: We have completed our review of your filing. We remind "
    "you that the company and its management are responsible for the accuracy and "
    "adequacy of their disclosures, notwithstanding any review."
)


def test_pdf_text_reads_text_operators():
    content = b"BT /F1 12 Tf (Re: Apple Inc.) Tj T* [(File No. ) -20 (001-36743)] TJ ET"
    pdf = b"%PDF-1.5\n1 0 obj<<>>stream\n" + zlib.compress(content) + b"\nendstream\n"
    assert CL.pdf_text(pdf) == "Re: Apple Inc. File No. 001-36743"


def test_parse_letters():
    p = CL.parse(SEC_LETTER, "UPLOAD")
    assert p["file_number"] == "001-36743" and p["kind"] == "letter"
    assert p["subject"].startswith("Apple Inc. Form 10-K for the fiscal year ended")
    assert p["topics"] == ["non_gaap", "segments"] and not p["closes_review"]
    closing = CL.parse(CLOSING, "UPLOAD")
    assert closing["closes_review"] and closing["topics"] == []  # boilerplate tags nothing
    accel = CL.parse(
        "Re: Example Corp. Registration Statement on Form S-1 Ladies and gentlemen: "
        "we request acceleration of the effective date to 4:00 p.m.",
        "CORRESP",
    )
    assert accel["kind"] == "acceleration_request" and accel["topics"] == []


def _letter(db, acc, form, filed, text):
    p = CL.parse(text, form)
    db.add(CommentLetter(accession_number=acc, cik=CIK, form_type=form, filing_date=filed,
                         file_number=p["file_number"], subject=p["subject"], kind=p["kind"],
                         readable=True, closes_review=p["closes_review"],
                         topics=json.dumps(p["topics"]), text=text,
                         source_url=f"https://www.sec.gov/Archives/edgar/data/320193/{acc}.pdf",
                         reader_version=CL.READER))  # fmt: skip


def test_threads_and_endpoint(client, auth, db, ingested_aapl):
    _letter(db, "0000000000-24-003120", "UPLOAD", date(2024, 3, 6), SEC_LETTER)
    _letter(db, "0000320193-24-900031", "CORRESP", date(2024, 3, 20),
            "Re: Apple Inc. File No. 001-36743 In response to the Staff's comment on our "
            "reportable segments and ASC 280 ...")  # fmt: skip
    _letter(db, "0000000000-24-005673", "UPLOAD", date(2024, 5, 16), CLOSING)
    _letter(
        db,
        "0000000000-26-000001",
        "UPLOAD",
        date(2026, 3, 1),  # a later review
        SEC_LETTER.replace("March 6, 2024", "March 1, 2026"),
    )
    db.commit()
    body = client.get(f"/v1/companies/{CIK}/comment-letters?since=2023-01-01", headers=auth).json()
    assert body["coverage"] == "read"
    threads = body["threads"]
    assert len(threads) == 2  # 21 months apart: two reviews
    old = threads[1]
    assert old["status"] == "closed" and old["closed"] == "2024-05-16"
    assert [x["from"] for x in old["letters"]] == ["sec", "company", "sec"]
    assert old["topics"] == ["non_gaap", "segments"] and old["file_number"] == "001-36743"
    assert "text" not in json.dumps(old["letters"][0])
    only = client.get(f"/v1/companies/{CIK}/comment-letters?topic=non_gaap&since=2023-01-01",
                      headers=auth).json()  # fmt: skip
    assert len(only["threads"]) == 2
    bad = client.get(f"/v1/companies/{CIK}/comment-letters?topic=nope", headers=auth)
    assert bad.status_code == 422


def test_not_read_lists_the_letters(client, auth, db, ingested_aapl):
    db.add(Filing(cik=CIK, accession_number="0000000000-25-000777", form_type="UPLOAD",
                  filing_date=date(2025, 6, 1), primary_document="filename1.pdf",
                  source_url="https://www.sec.gov/Archives/edgar/data/320193/x-index.html",
                  first_detected_at=utcnow(), quality_status="ok"))  # fmt: skip
    db.commit()
    body = client.get(f"/v1/companies/{CIK}/comment-letters", headers=auth).json()
    assert body["coverage"] == "not_read" and body["letters"][0]["from"] == "sec"


def test_no_review_letters_carry_no_topics():
    p = CL.parse(
        "Re: Example Corp. Registration Statement on Form S-4 File No. 333-123456 Dear "
        "Ms. Doe: This is to advise you that we have not reviewed and will not review "
        "your registration statement. Please refer to Rules 460 and 461.",
        "UPLOAD",
    )
    assert p["kind"] == "no_review" and p["closes_review"] and p["topics"] == []
    gov = CL.parse(
        "Re: Example Corp. Definitive Proxy Statement File No. 001-12345 Dear Mr. Doe: "
        "Please expand your discussion of the reasons you believe that your "
        "leadership structure is appropriate.",
        "UPLOAD",
    )
    assert gov["topics"] == ["governance"]


def _ask(client, auth, q, **kw):
    r = client.post("/v1/chat", json={"message": q, "cik": CIK, **kw}, headers=auth).json()
    assert r["intent"] == "comment_letters" and r["answered_by"] == "data", r
    return r


def test_comment_letters_chat_answer_with_a_table(client, auth, db, ingested_aapl):
    """C-16: chat answers from the letters read (D-13), cited, with the existing table block."""
    from app.services.chat_intents import detect

    assert detect("Has the SEC sent Apple any comment letters?") == "comment_letters"
    assert detect("What did SEC staff comments to Apple cover?") == "comment_letters"
    assert detect("Who are Apple's largest holders?") == "holders"  # unchanged
    _letter(db, "0000000000-24-003120", "UPLOAD", date(2024, 3, 6), SEC_LETTER)
    _letter(db, "0000000000-24-005673", "UPLOAD", date(2024, 5, 16), CLOSING)
    _letter(db, "0000000000-26-000001", "UPLOAD", date(2026, 3, 1),
            SEC_LETTER.replace("March 6, 2024", "March 1, 2026"))  # fmt: skip
    db.commit()
    r = _ask(client, auth, "Has the SEC sent Apple any comment letters?", as_of="2026-11-24")
    a = r["answer"]
    assert a.startswith("Apple Inc. has 2 SEC comment-letter reviews since 2021-11-24")
    assert "The latest opened 2026-03-01 (file 001-36743) on Non-GAAP measures, Segment " \
        "reporting; no closing letter is in the letters read here [" in a  # fmt: skip
    assert "Non-GAAP measures (2), Segment reporting (2)" in a and "not read by a model" in a
    n = int(a.split("[")[1].split("]")[0])
    cite = next(c for c in r["citations"] if c["n"] == n)
    assert cite["url"].endswith("0000000000-26-000001.pdf")
    table = next(b for b in r["blocks"] if b["type"] == "table")
    assert table["columns"] == ["Opened", "Closed", "File number", "Subject", "Topics", "Letters"]
    assert [row[0]["text"] for row in table["rows"]] == ["2026-03-01", "2024-03-06"]
    assert table["rows"][1][1]["text"] == "2024-05-16"
    assert all(row[0]["url"].startswith("https://www.sec.gov/Archives/") for row in table["rows"])
    assert r["widgets"] == [table]
    # as_of before the closing letter: that review is still open, the later one unknown
    early = _ask(client, auth, "Any SEC comment letters for Apple?", as_of="2024-04-01")
    assert "has 1 SEC comment-letter review since" in early["answer"]
    assert "no closing letter is in the letters read here" in early["answer"]


def test_comment_letters_chat_not_read_lists_the_filings(client, auth, db, ingested_aapl):
    db.add(Filing(cik=CIK, accession_number="0000000000-25-000777", form_type="UPLOAD",
                  filing_date=date(2025, 6, 1), primary_document="filename1.pdf",
                  source_url="https://www.sec.gov/Archives/edgar/data/320193/x-index.html",
                  first_detected_at=utcnow(), quality_status="ok"))  # fmt: skip
    db.commit()
    a = _ask(client, auth, "Show Apple's SEC comment letters", as_of="2026-11-24")
    assert "have not been read here yet, so their topics are not known" in a["answer"]
    assert "the latest is the SEC's letter filed 2025-06-01 [" in a["answer"]
    table = next(b for b in a["blocks"] if b["type"] == "table")
    assert table["rows"][0][0] == {"text": "2025-06-01", "url": "https://www.sec.gov/Archives/"
                                   "edgar/data/320193/x-index.html"}  # fmt: skip


def test_executive_compensation_topic():
    """C-13b (2026-11-24): Item 402 letters (pay versus performance, CD&A, the Summary
    Compensation Table) get the executive_compensation topic; other topics stay as they were."""
    pvp = ("Re: Example Corp. Definitive Proxy Statement on Schedule 14A File No. 001-12345 "
           "Pay Versus Performance Table, page 8 1. Item 402(v)(2)(iii) of Regulation S-K "
           "specifies the calculations required to derive compensation actually paid. We note "
           "your use of Adjusted EBITDA, a non-GAAP measure.")  # fmt: skip
    assert CL.parse(pvp, "UPLOAD")["topics"] == ["non_gaap", "executive_compensation"]
    assert CL.TOPIC_LABELS["executive_compensation"] == "Executive compensation"
    assert "executive_compensation" not in CL.parse(SEC_LETTER, "UPLOAD")["topics"]
    assert CL.parse(SEC_LETTER, "UPLOAD")["topics"] == ["non_gaap", "segments"]
