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
