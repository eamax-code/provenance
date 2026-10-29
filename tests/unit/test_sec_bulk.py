import json
import zipfile
from pathlib import Path

import httpx
import pytest
from sqlalchemy import func, select

from app.db.models import Company, Filing, FinancialFact, IngestionRun, UniverseMember
from app.services import sec_bulk
from app.services.sec_client import SecClient, SecClientError

FIX = Path(__file__).parents[1] / "fixtures"


def _build_archives(tmp_path):
    subs, facts = tmp_path / "submissions.zip", tmp_path / "companyfacts.zip"
    with zipfile.ZipFile(subs, "w") as zf:
        zf.writestr("CIK0000320193.json", (FIX / "submissions_0000320193.json").read_text())
        zf.writestr("CIK0000789019.json", (FIX / "submissions_0000789019.json").read_text())
        zf.writestr(
            "CIK0000320193-submissions-001.json",
            (FIX / "submissions_0000320193_page1.json").read_text(),
        )
        zf.writestr(
            "CIK0001234567.json",
            json.dumps({"cik": "1234567", "name": "A PERSON", "filings": {"recent": {}}}),
        )
    with zipfile.ZipFile(facts, "w") as zf:
        zf.writestr("CIK0000320193.json", (FIX / "companyfacts_0000320193.json").read_text())
        zf.writestr("CIK0000789019.json", (FIX / "companyfacts_0000789019.json").read_text())
    return subs, facts


def test_scope_facts_ingests_xbrl_filers_and_matches_api_path(db, settings, tmp_path, sec_client):
    subs, facts = _build_archives(tmp_path)
    summary = sec_bulk.bulk_ingest(db, settings, subs, facts, scope="facts")
    assert summary["selected"] == 2 and summary["ingested"] == 2 and summary["failed"] == 0
    assert (
        db.scalar(select(func.count(Company.id))) == 2
    )  # the individual filer without facts is not selected
    aapl_filings = db.scalar(select(func.count(Filing.id)).where(Filing.cik == "0000320193"))
    aapl_facts = db.scalar(
        select(func.count(FinancialFact.id)).where(FinancialFact.cik == "0000320193")
    )
    # The same company through the per-company API path yields identical rows (idempotent no-op).
    from app.services.ingestion import ingest_company

    again = ingest_company(db, sec_client, "320193")
    assert again.filings_inserted == 0 and again.facts_inserted == 0
    assert aapl_filings == 6 and aapl_facts > 0
    f = db.scalar(select(Filing).where(Filing.accession_number == "0000320193-24-000123"))
    assert f.source_url.startswith("https://www.sec.gov/Archives/edgar/data/320193/")
    c = db.scalar(select(Company).where(Company.cik == "0000320193"))
    assert c.source_url == "https://data.sec.gov/submissions/CIK0000320193.json"
    run = db.scalar(select(IngestionRun).where(IngestionRun.source == "sec:bulk"))
    assert run.status == "succeeded" and run.sec_cached > 0


def test_scope_known_and_ciks_and_limit(db, settings, tmp_path, tickers_payload):
    from app.services.ingestion import import_ticker_mapping

    subs, facts = _build_archives(tmp_path)
    import_ticker_mapping(db, tickers_payload)  # 5 known companies, 2 present in the archive
    db.commit()
    client = sec_bulk.ArchiveClient(settings, subs, facts)
    try:
        assert sec_bulk.select_ciks(db, client, "known") == ["0000320193", "0000789019"]
        assert sec_bulk.select_ciks(db, client, "ciks", ["789019", "999"]) == ["0000789019"]
        assert sec_bulk.select_ciks(db, client, "facts", limit=1) == ["0000320193"]
        assert client.ciks_with_submissions() == ["0000320193", "0000789019", "0001234567"]
        with pytest.raises(ValueError):
            sec_bulk.select_ciks(db, client, "everything")
    finally:
        client.close()


def test_missing_facts_and_history_pages_from_archive(db, settings, tmp_path, monkeypatch):
    subs, _ = _build_archives(tmp_path)
    monkeypatch.setattr(settings, "sec_filings_history_pages", 1)
    payload = json.loads((FIX / "submissions_0000320193.json").read_text())
    payload["filings"]["files"] = [{"name": "CIK0000320193-submissions-001.json"}]
    with zipfile.ZipFile(subs, "a") as zf:
        zf.writestr("CIK0000320193.json", json.dumps(payload))  # duplicate name: last wins on read
    summary = sec_bulk.bulk_ingest(db, settings, subs, None, scope="ciks", ciks=["320193"])
    assert summary["ingested"] == 1 and summary["facts_unavailable"] == 1
    assert db.scalar(select(func.count(Filing.id))) == 8  # 6 recent + 2 new from the history page


def test_universe_scope_marks_members_refreshed(db, settings, tmp_path):
    from app.services import universe

    subs, facts = _build_archives(tmp_path)
    universe.seed_from_lines(db, ["320193"], source="file")
    db.commit()
    summary = sec_bulk.bulk_ingest(db, settings, subs, facts, scope="universe")
    assert summary["ingested"] == 1
    assert db.scalar(select(UniverseMember)).last_success_at is not None


def test_download_file_streams_revalidates_and_caps(settings, tmp_path):
    body = b"PK" + b"x" * 5000
    calls = []

    def handler(request):
        calls.append(dict(request.headers))
        if request.headers.get("If-Modified-Since"):
            return httpx.Response(304)
        return httpx.Response(
            200, content=body, headers={"Last-Modified": "Wed, 29 Oct 2026 03:00:00 GMT"}
        )

    client = SecClient(
        settings, http=httpx.Client(transport=httpx.MockTransport(handler)), sleep=lambda s: None
    )
    dest = tmp_path / "bulk" / "submissions.zip"
    first = client.download_file("https://www.sec.gov/x/submissions.zip", dest)
    assert (
        first["from_cache"] is False
        and dest.read_bytes() == body
        and first["last_modified"].year == 2026
    )
    second = client.download_file("https://www.sec.gov/x/submissions.zip", dest)
    assert (
        second["from_cache"] is True
        and calls[1]["if-modified-since"] == "Wed, 29 Oct 2026 03:00:00 GMT"
    )
    with pytest.raises(SecClientError):
        client.download_file("https://www.sec.gov/x/big.zip", tmp_path / "big.zip", max_bytes=100)
    assert not (tmp_path / "big.zip.part").exists()


def test_download_retries_then_succeeds(settings, tmp_path):
    seq = [503, 200]

    def handler(request):
        code = seq.pop(0)
        return httpx.Response(
            code, content=b"ok" if code == 200 else b"", headers={"Retry-After": "0"}
        )

    client = SecClient(
        settings, http=httpx.Client(transport=httpx.MockTransport(handler)), sleep=lambda s: None
    )
    out = client.download_file("https://www.sec.gov/x/f.zip", tmp_path / "f.zip")
    assert out["bytes"] == 2 and client.metrics.retries == 1
