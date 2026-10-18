import httpx

from app.jobs.poll_sec import run_once, single_run_guard, watched_ciks


def test_run_once_polls_watched_companies_and_delivers(
    db, settings, sec_client, fake_sec, submissions_aapl, tickers_payload
):
    from datetime import UTC, datetime

    from app.db.models import CompanyWatch
    from app.services.api_keys import create_key_record
    from app.services.ingestion import import_ticker_mapping, ingest_company
    from app.services.notifications import WebhookSender

    import_ticker_mapping(db, tickers_payload)
    ingest_company(db, sec_client, "320193")
    key, _ = create_key_record(db, settings, "p@example.com", "free", None, actor="test")
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
    assert watched_ciks(db) == ["0000320193"]
    assert set(watched_ciks(db, include_all_companies=True)) == {"0000320193"}

    recent = {k: list(v) for k, v in submissions_aapl["filings"]["recent"].items()}
    for col, val in [
        ("accessionNumber", "0000320193-25-000002"),
        ("filingDate", "2026-10-15"),
        ("reportDate", ""),
        ("acceptanceDateTime", ""),
        ("form", "8-K"),
        ("primaryDocument", "y.htm"),
    ]:
        recent[col].insert(0, val)
    fake_sec.add(
        "https://data.sec.gov/submissions/CIK0000320193.json",
        {**submissions_aapl, "filings": {"recent": recent}},
    )

    sent = []

    class NoDNS(WebhookSender):
        def send(self, url, body, headers):
            return self.http.post(url, content=body, headers=headers)

    sender = NoDNS(
        settings,
        http=httpx.Client(
            transport=httpx.MockTransport(lambda r: (sent.append(r), httpx.Response(200))[1])
        ),
    )
    summary = run_once(db, settings, client=sec_client, sender=sender)
    assert (
        summary["companies"] == 1
        and summary["succeeded"] == 1
        and summary["notifications_created"] == 1
    )
    assert summary["deliveries"]["delivered"] == 1 and len(sent) == 1


def test_poll_continues_after_one_company_fails(
    db, settings, sec_client, fake_sec, tickers_payload
):
    from datetime import UTC, datetime

    from sqlalchemy import select

    from app.db.models import CompanyWatch, IngestionRun
    from app.services.api_keys import create_key_record
    from app.services.ingestion import import_ticker_mapping

    import_ticker_mapping(db, tickers_payload)
    key, _ = create_key_record(db, settings, "p@example.com", "free", None, actor="test")
    for cik in ("0000320193", "0001318605"):  # TSLA has no fixture -> 404
        db.add(
            CompanyWatch(
                api_key_id=key.id,
                cik=cik,
                destination_type="webhook",
                destination="https://hooks.example.com/",
                is_active=True,
                created_at=datetime.now(UTC),
            )
        )
    db.commit()
    summary = run_once(db, settings, client=sec_client)
    assert summary["succeeded"] == 1 and summary["failed"] == 1
    run = db.scalar(select(IngestionRun).where(IngestionRun.source == "sec:poll"))
    assert run.status == "partial" and "0001318605" in run.error_summary


def test_single_run_guard_blocks_concurrent_runner(db, tmp_path):
    """A second runner (separate session/connection) must not acquire the lock."""
    from app.db.session import session_factory

    lock = str(tmp_path / "lock")
    other = session_factory()()
    try:
        with single_run_guard(db, lock_file=lock) as a:
            assert a is True
            with single_run_guard(other, lock_file=lock) as b:
                assert b is False
        with single_run_guard(other, lock_file=lock) as c:
            assert c is True
    finally:
        other.close()
