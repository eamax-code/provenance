from datetime import date

from app.services.form_names import form_label, form_phrase, human_date


def test_plain_form_names_and_dates():
    assert form_phrase("4") == "an insider trade report (Form 4)"
    assert form_phrase("10-K") == "an annual report (10-K)"
    assert form_phrase("424B4") == "a final prospectus (424B4)"
    assert form_label("8-K") == "Current report (8-K)"
    assert form_label("SC 13G") == "5% holder report (SC 13G)"
    assert form_phrase("N-PX") == "an N-PX filing" and form_label("N-PX") == "N-PX"
    assert (
        human_date(date(2026, 9, 26)) == "26 Sep 2026" and human_date("2026-01-05") == "5 Jan 2026"
    )
    assert human_date(None) == ""
