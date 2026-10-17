from datetime import UTC, date, datetime

import pytest

from app.services.ingestion import IngestionError, parse_submissions, parse_timestamp


def test_parse_submissions_basic(submissions_aapl):
    company, filings = parse_submissions(submissions_aapl)
    assert company.cik == "0000320193" and company.ticker == "AAPL" and company.exchange == "Nasdaq"
    assert company.source_url == "https://data.sec.gov/submissions/CIK0000320193.json"
    assert len(filings) == 6
    f = filings[0]
    assert f.accession_number == "0000320193-24-000123" and f.form_type == "10-K"
    assert f.filing_date == date(2024, 11, 1)
    assert f.accepted_at == datetime(2024, 11, 1, 6, 1, 36, tzinfo=UTC)
    assert f.quality_status == "ok"
    assert f.source_url.endswith("/0000320193-24-000123-index.html")


def test_missing_acceptance_timestamp_stays_null_and_marks_partial(submissions_aapl):
    _, filings = parse_submissions(submissions_aapl)
    eight_k = next(f for f in filings if f.form_type == "8-K")
    assert eight_k.accepted_at is None and eight_k.report_date is None
    assert eight_k.quality_status == "partial"
    assert any("timestamp" in n for n in eight_k.notes)


@pytest.mark.parametrize("value", ["2024-11-01", "", None, "garbage", "2024-11-01T"])
def test_parse_timestamp_never_infers_from_date_only(value):
    assert parse_timestamp(value) is None


def test_parse_timestamp_normalizes_timezone():
    assert parse_timestamp("2024-11-01T02:01:36.000-04:00") == datetime(
        2024, 11, 1, 6, 1, 36, tzinfo=UTC
    )
    assert parse_timestamp("2024-11-01T06:01:36").tzinfo is UTC


def test_parse_submissions_handles_empty_and_malformed(submissions_aapl):
    company, filings = parse_submissions({"cik": "1", "name": "X", "filings": {}})
    assert company.cik == "0000000001" and filings == []
    company, filings = parse_submissions(
        {"cik": "1", "name": "X", "filings": {"recent": {"accessionNumber": "nope"}}}
    )
    assert filings == []
    # column length mismatch -> missing columns treated as absent
    payload = {
        "cik": "1",
        "name": "X",
        "filings": {"recent": {"accessionNumber": ["0000000001-24-000001"], "form": []}},
    }
    _, filings = parse_submissions(payload)
    assert filings[0].form_type == "UNKNOWN" and filings[0].quality_status == "partial"
    with pytest.raises(IngestionError):
        parse_submissions({"name": "no cik"})
    with pytest.raises(IngestionError):
        parse_submissions({"cik": "abc", "name": "bad cik"})
    with pytest.raises(IngestionError):
        parse_submissions({"cik": "1"})


def test_parse_submissions_drops_duplicate_and_invalid_accessions():
    payload = {
        "cik": "1",
        "name": "X",
        "filings": {
            "recent": {
                "accessionNumber": ["0000000001-24-000001", "0000000001-24-000001", "bad-accn", ""],
                "form": ["10-K", "10-K", "10-K", "10-K"],
                "filingDate": ["2024-01-01"] * 4,
            }
        },
    }
    _, filings = parse_submissions(payload)
    assert [f.accession_number for f in filings] == ["0000000001-24-000001"]
