from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select

from app.db.models import Company, Filing, FinancialFact, IngestionRun
from app.services.ingestion import ingest_company
from app.services.sec_client import SecNotFound, SecUnavailable


def test_ingest_company_vertical_slice(db, sec_client):
    result = ingest_company(db, sec_client, "320193")
    assert result.filings_seen == 6 and result.filings_inserted == 6
    assert result.facts_inserted == result.facts_seen > 0
    company = db.scalar(select(Company).where(Company.cik == "0000320193"))
    assert company.legal_name == "Apple Inc." and company.last_processed_at is not None
    assert company.last_successful_fetch_at is not None and company.quality_status == "ok"
    assert company.source_updated_at is not None  # from Last-Modified header
    run = db.get(IngestionRun, result.run_id)
    assert run.status == "succeeded" and run.filings_seen == 6 and run.finished_at is not None


def test_repeated_ingestion_is_idempotent(db, sec_client):
    first = ingest_company(db, sec_client, "320193")
    filings_before = {
        f.accession_number: (f.first_detected_at, f.processed_at)
        for f in db.scalars(select(Filing))
    }
    facts_before = db.scalar(select(func.count(FinancialFact.id)))
    second = ingest_company(db, sec_client, "320193")
    assert second.filings_inserted == 0 and second.filings_updated == 0
    assert second.facts_inserted == 0 and second.facts_updated == 0
    assert db.scalar(select(func.count(Filing.id))) == len(filings_before)
    assert db.scalar(select(func.count(FinancialFact.id))) == facts_before
    for f in db.scalars(select(Filing)):
        assert f.first_detected_at == filings_before[f.accession_number][0]
    assert first.run_id != second.run_id


def test_changed_filing_metadata_updates_without_duplicating(
    db, sec_client, fake_sec, submissions_aapl
):
    ingest_company(db, sec_client, "320193")
    changed = dict(submissions_aapl)
    changed["filings"] = {"recent": dict(submissions_aapl["filings"]["recent"])}
    changed["filings"]["recent"]["form"] = ["10-K/A"] + submissions_aapl["filings"]["recent"][
        "form"
    ][1:]
    fake_sec.add("https://data.sec.gov/submissions/CIK0000320193.json", changed)
    result = ingest_company(db, sec_client, "320193")
    assert result.filings_inserted == 0 and result.filings_updated == 1
    f = db.scalar(select(Filing).where(Filing.accession_number == "0000320193-24-000123"))
    assert f.form_type == "10-K/A" and db.scalar(select(func.count(Filing.id))) == 6


def test_new_filing_detected_on_second_run(db, sec_client, fake_sec, submissions_aapl):
    ingest_company(db, sec_client, "320193")
    recent = {k: list(v) for k, v in submissions_aapl["filings"]["recent"].items()}
    recent["accessionNumber"].insert(0, "0000320193-25-000001")
    recent["filingDate"].insert(0, "2025-01-31")
    recent["reportDate"].insert(0, "2024-12-28")
    recent["acceptanceDateTime"].insert(0, "2025-01-31T06:00:00.000Z")
    recent["form"].insert(0, "10-Q")
    recent["primaryDocument"].insert(0, "aapl-20241228.htm")
    fake_sec.add(
        "https://data.sec.gov/submissions/CIK0000320193.json",
        {**submissions_aapl, "filings": {"recent": recent}},
    )
    result = ingest_company(db, sec_client, "320193")
    assert result.filings_inserted == 1 and len(result.new_filing_ids) == 1


def test_sec_not_found_records_failure(db, sec_client):
    with pytest.raises(SecNotFound):
        ingest_company(db, sec_client, "999")
    run = db.scalar(select(IngestionRun))
    assert run.status == "failed" and run.error_count == 1


def test_sec_unavailable_keeps_last_good_data_and_records_error(db, sec_client, fake_sec):
    ingest_company(db, sec_client, "320193")
    fake_sec.fail_statuses = [503, 503, 503, 503]
    with pytest.raises(SecUnavailable):
        ingest_company(db, sec_client, "320193")
    company = db.scalar(select(Company).where(Company.cik == "0000320193"))
    assert company.last_fetch_error and company.last_fetch_error_at is not None
    assert company.last_successful_fetch_at is not None  # retained
    assert db.scalar(select(func.count(Filing.id))) == 6


def test_facts_missing_marks_company_partial(db, sec_client, fake_sec, submissions_aapl):
    fake_sec.routes.pop("https://data.sec.gov/api/xbrl/companyfacts/CIK0000320193.json")
    result = ingest_company(db, sec_client, "320193")
    assert result.facts_available is False and result.facts_seen == 0
    company = db.scalar(select(Company).where(Company.cik == "0000320193"))
    assert company.quality_status == "partial"


def test_timestamps_are_utc_aware(db, sec_client):
    ingest_company(db, sec_client, "320193")
    f = db.scalar(select(Filing).where(Filing.accession_number == "0000320193-24-000123"))
    assert f.accepted_at.tzinfo is not None and f.accepted_at.utcoffset() == timedelta(0)
    assert f.first_detected_at.tzinfo is not None
    assert abs((datetime.now(UTC) - f.first_detected_at).total_seconds()) < 60
