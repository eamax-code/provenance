from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select

from app.db.models import Filing, UniverseMember
from app.services import universe
from app.services.sec_client import SecNotFound


def _now():
    return datetime(2026, 10, 18, 12, 0, tzinfo=UTC)


def test_seed_from_tickers_top_n_dedupes_and_sets_priority(db, tickers_payload):
    stats = universe.seed_from_tickers(db, tickers_payload, top_n=3)
    db.commit()
    assert stats["added"] == 3
    members = db.scalars(select(UniverseMember).order_by(UniverseMember.priority)).all()
    assert [m.cik for m in members] == ["0000320193", "0000789019", "0001652044"]
    assert all(m.source == "tickers" and m.is_active for m in members)
    again = universe.seed_from_tickers(db, tickers_payload, top_n=5)
    assert again["added"] == 2 and db.scalar(select(func.count(UniverseMember.id))) == 5


def test_seed_from_lines_accepts_any_cik_padding_and_skips_junk(db):
    stats = universe.seed_from_lines(
        db, ["320193", "# comment", "", "CIK0000789019", "not-a-cik", "320193"], source="file"
    )
    db.commit()
    assert stats["added"] == 2 and stats["skipped"] == 1
    assert {m.cik for m in db.scalars(select(UniverseMember))} == {"0000320193", "0000789019"}


def test_due_members_ordered_by_priority_then_next_attempt(db):
    universe.seed_from_lines(db, ["3", "1", "2"], source="file")
    db.commit()
    m1 = universe.get_member(db, "0000000001")
    m1.next_attempt_at = _now() + timedelta(hours=1)  # not due
    db.commit()
    due = universe.due_members(db, limit=10, now=_now())
    assert [m.cik for m in due] == ["0000000003", "0000000002"]


def test_bulk_ingest_respects_budget_and_resumes(
    db, settings, sec_client, fake_sec, tickers_payload
):
    universe.seed_from_tickers(db, tickers_payload, top_n=2)  # AAPL, MSFT
    db.commit()
    # each company costs 2 requests (submissions + facts); budget of 2 => one company per run
    first = universe.bulk_ingest(db, settings, sec_client, request_budget=2, now=_now())
    assert first["ingested"] == 1 and first["remaining_due"] == 1
    second = universe.bulk_ingest(db, settings, sec_client, request_budget=2, now=_now())
    assert second["ingested"] == 1 and second["remaining_due"] == 0
    third = universe.bulk_ingest(db, settings, sec_client, request_budget=10, now=_now())
    assert third["ingested"] == 0  # nothing due until the refresh interval elapses
    members = {m.cik: m for m in db.scalars(select(UniverseMember))}
    assert all(
        m.last_success_at == _now() and m.consecutive_failures == 0 for m in members.values()
    )
    later = _now() + timedelta(seconds=settings.universe_refresh_interval_seconds + 1)
    assert (
        universe.bulk_ingest(db, settings, sec_client, request_budget=10, now=later)["ingested"]
        == 2
    )


def test_failures_back_off_and_eventually_disable(db, settings, sec_client, monkeypatch):
    universe.seed_from_lines(db, ["999"], source="file")  # no fixture -> SEC 404
    db.commit()
    monkeypatch.setattr(settings, "universe_max_consecutive_failures", 3)
    now = _now()
    for i in range(3):
        result = universe.bulk_ingest(db, settings, sec_client, request_budget=10, now=now)
        assert result["failed"] == 1
        m = universe.get_member(db, "0000000999")
        assert m.consecutive_failures == i + 1
        if i < 2:
            assert m.is_active and m.next_attempt_at > now
            now = m.next_attempt_at
    assert m.is_active is False and "consecutive failures" in m.disabled_reason
    assert (
        universe.bulk_ingest(
            db, settings, sec_client, request_budget=10, now=now + timedelta(days=5)
        )["ingested"]
        == 0
    )


def test_backoff_grows_and_is_capped():
    assert universe.failure_backoff_seconds(1) == 15 * 60
    assert universe.failure_backoff_seconds(2) == 30 * 60
    assert universe.failure_backoff_seconds(10) == 24 * 3600


def test_history_pages_are_ingested_without_duplicates(
    db, settings, sec_client, fake_sec, submissions_aapl
):
    import json
    from pathlib import Path

    from app.services.ingestion import ingest_company

    page = json.loads(
        (Path(__file__).parents[1] / "fixtures/submissions_0000320193_page1.json").read_text()
    )
    payload = {
        **submissions_aapl,
        "filings": {
            **submissions_aapl["filings"],
            "files": [
                {
                    "name": "CIK0000320193-submissions-001.json",
                    "filingCount": 3,
                    "filingFrom": "2022-06-25",
                    "filingTo": "2024-11-01",
                }
            ],
        },
    }
    fake_sec.add("https://data.sec.gov/submissions/CIK0000320193.json", payload)
    fake_sec.add("https://data.sec.gov/submissions/CIK0000320193-submissions-001.json", page)
    result = ingest_company(db, sec_client, "320193", history_pages=0)
    assert result.filings_inserted == 6
    result = ingest_company(db, sec_client, "320193", history_pages=1)
    assert (
        result.filings_inserted == 2 and result.history_pages_fetched == 1
    )  # 1 of 3 page rows is a duplicate
    assert db.scalar(select(func.count(Filing.id)).where(Filing.cik == "0000320193")) == 8
    assert (
        db.scalar(
            select(func.count(Filing.id)).where(Filing.accession_number == "0000320193-24-000123")
        )
        == 1
    )


def test_watched_ciks_are_added_to_universe_on_poll(db, settings, sec_client, tickers_payload):
    from datetime import datetime as dt

    from app.db.models import CompanyWatch
    from app.jobs.poll_sec import run_once
    from app.services.api_keys import create_key_record
    from app.services.ingestion import import_ticker_mapping

    import_ticker_mapping(db, tickers_payload)
    key, _ = create_key_record(db, settings, "p@example.com", "free", None, actor="test")
    db.add(
        CompanyWatch(
            api_key_id=key.id,
            cik="0000320193",
            destination_type="webhook",
            destination="https://hooks.example.com/",
            is_active=True,
            created_at=dt.now(UTC),
        )
    )
    db.commit()
    summary = run_once(db, settings, client=sec_client)
    assert summary["succeeded"] == 1
    m = universe.get_member(db, "0000320193")
    assert m is not None and m.source == "watch" and m.last_success_at is not None


def test_not_found_at_sec_is_a_counted_failure(db, settings, sec_client):
    universe.seed_from_lines(db, ["999"], source="file")
    db.commit()
    with pytest.raises(SecNotFound):
        from app.services.ingestion import ingest_company

        ingest_company(db, sec_client, "999")


def test_run_once_refreshes_due_universe_members_within_budget(
    db, settings, sec_client, tickers_payload
):
    from app.jobs.poll_sec import run_once

    universe.seed_from_tickers(db, tickers_payload, top_n=2)  # AAPL, MSFT; no watches
    db.commit()
    summary = run_once(db, settings, client=sec_client)
    assert summary["companies"] == 0 and summary["universe"]["ingested"] == 2
    assert summary["universe"]["requests_used"] >= 4
    again = run_once(db, settings, client=sec_client)
    assert again["universe"]["ingested"] == 0  # refreshed recently, nothing due
    summary_off = run_once(db, settings, client=sec_client, include_universe=False)
    assert "universe" not in summary_off


def test_bulk_ingest_charges_actual_requests_including_retries(
    db, settings, sec_client, fake_sec, tickers_payload
):
    universe.seed_from_tickers(db, tickers_payload, top_n=1)
    db.commit()
    fake_sec.fail_statuses = [503]
    summary = universe.bulk_ingest(db, settings, sec_client, request_budget=10, now=_now())
    assert summary["ingested"] == 1 and summary["requests_used"] == 3


def test_history_page_and_old_filings_never_notify(
    db, settings, sec_client, fake_sec, submissions_aapl
):
    import json
    from pathlib import Path

    from sqlalchemy import select

    from app.db.models import CompanyWatch, NotificationDelivery
    from app.services.api_keys import create_key_record
    from app.services.ingestion import ingest_company

    ingest_company(db, sec_client, "320193")
    key, _ = create_key_record(db, settings, "w@example.com", "free", None, actor="test")
    db.add(
        CompanyWatch(
            api_key_id=key.id,
            cik="0000320193",
            destination_type="webhook",
            destination="https://hooks.example.com/",
            is_active=True,
            created_at=datetime.now(UTC),
        )
    )
    db.commit()
    page = json.loads(
        (Path(__file__).parents[1] / "fixtures/submissions_0000320193_page1.json").read_text()
    )
    recent = {k: list(v) for k, v in submissions_aapl["filings"]["recent"].items()}
    # a filing dated years ago appearing in `recent` for the first time is backfill too
    for col, val in [
        ("accessionNumber", "0000320193-19-000001"),
        ("filingDate", "2019-01-31"),
        ("reportDate", ""),
        ("acceptanceDateTime", ""),
        ("form", "8-K"),
        ("primaryDocument", "old.htm"),
    ]:
        recent[col].insert(0, val)
    payload = {
        **submissions_aapl,
        "filings": {"recent": recent, "files": [{"name": "CIK0000320193-submissions-001.json"}]},
    }
    fake_sec.add("https://data.sec.gov/submissions/CIK0000320193.json", payload)
    fake_sec.add("https://data.sec.gov/submissions/CIK0000320193-submissions-001.json", page)
    result = ingest_company(
        db, sec_client, "320193", history_pages=1, now=datetime(2026, 10, 18, tzinfo=UTC)
    )
    assert result.filings_inserted == 3 and result.notifications_created == 0
    assert db.scalars(select(NotificationDelivery)).all() == []


def test_unexpected_error_mid_ingest_rolls_back_partial_writes(
    db, settings, sec_client, monkeypatch
):
    from sqlalchemy import func, select

    from app.db.models import Company, Filing, IngestionRun
    from app.services import ingestion

    def boom(*a, **k):
        raise RuntimeError("disk on fire")

    monkeypatch.setattr(ingestion, "upsert_filings", boom)
    with pytest.raises(RuntimeError):
        ingestion.ingest_company(db, sec_client, "320193")
    assert db.scalar(select(func.count(Company.id))) == 0
    assert db.scalar(select(func.count(Filing.id))) == 0
    runs = db.scalars(select(IngestionRun)).all()
    assert len(runs) == 1 and runs[0].status == "failed" and runs[0].sec_requests == 1
