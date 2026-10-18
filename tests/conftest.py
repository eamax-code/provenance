from __future__ import annotations

import json
import os
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

FIXTURES = Path(__file__).parent / "fixtures"

TEST_ENV = {
    "APP_ENV": "test",
    "SEC_USER_AGENT": "Provenance-tests/0.1 contact=tests@provenance.test",
    "API_KEY_PEPPER": "test-pepper-0123456789abcdef",
    "WEBHOOK_SIGNING_SECRET": "test-webhook-master-0123456789abcdef",
    "ADMIN_TOKEN": "test-admin-token-0123456789",
    "SEC_MIN_REQUEST_INTERVAL_SECONDS": "0",
    "SEC_MAX_RETRIES": "2",
    "LOG_JSON": "false",
    "LOG_LEVEL": "WARNING",
    "WEBHOOK_RETRY_BASE_SECONDS": "1",
    "WEBHOOK_MAX_ATTEMPTS": "3",
    "FRESHNESS_STALE_AFTER_SECONDS": "86400",
}


@pytest.fixture(scope="session", autouse=True)
def _env():
    for k, v in TEST_ENV.items():
        os.environ[k] = v
    yield


@pytest.fixture
def settings(tmp_path):
    from app.core.config import Settings

    # Set TEST_DATABASE_URL=postgresql+psycopg://... to run the suite against PostgreSQL.
    database_url = os.environ.get("TEST_DATABASE_URL") or f"sqlite:///{tmp_path / 'test.sqlite3'}"
    if not database_url.startswith("sqlite") and "test" not in database_url.rsplit("/", 1)[-1]:
        raise RuntimeError(
            "The suite drops and recreates every table; TEST_DATABASE_URL must point at a "
            "database whose name contains 'test'."
        )
    return Settings(
        database_url=database_url,
        sec_cache_dir=str(tmp_path / "sec_cache"),
        **{k.lower(): v for k, v in TEST_ENV.items()},
    )


@pytest.fixture
def engine(settings):
    from app.db.models import Base
    from app.db.session import make_engine, set_engine

    eng = make_engine(settings.database_url)
    Base.metadata.drop_all(eng)
    Base.metadata.create_all(eng)
    set_engine(eng)
    yield eng
    Base.metadata.drop_all(eng)
    eng.dispose()


@pytest.fixture
def db(engine) -> Session:
    from app.db.session import session_factory

    session = session_factory()()
    yield session
    session.close()


def load_fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text("utf-8"))


@pytest.fixture
def submissions_aapl():
    return load_fixture("submissions_0000320193.json")


@pytest.fixture
def facts_aapl():
    return load_fixture("companyfacts_0000320193.json")


@pytest.fixture
def submissions_msft():
    return load_fixture("submissions_0000789019.json")


@pytest.fixture
def facts_msft():
    return load_fixture("companyfacts_0000789019.json")


@pytest.fixture
def tickers_payload():
    return load_fixture("company_tickers_exchange.json")


class FakeSEC:
    """httpx MockTransport serving fixture payloads for SEC URLs with ETag support."""

    def __init__(self):
        self.routes: dict[str, tuple[int, dict | None]] = {}
        self.calls: list[str] = []
        self.fail_statuses: list[int] = []

    def add(self, url: str, payload: dict | None, status: int = 200):
        self.routes[url] = (status, payload)

    def handler(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        self.calls.append(url)
        if self.fail_statuses:
            status = self.fail_statuses.pop(0)
            return httpx.Response(status, headers={"Retry-After": "0"})
        if url not in self.routes:
            return httpx.Response(404)
        status, payload = self.routes[url]
        if status != 200:
            return httpx.Response(status)
        body = json.dumps(payload).encode()
        etag = '"' + str(hash(body)) + '"'
        if request.headers.get("If-None-Match") == etag:
            return httpx.Response(304)
        return httpx.Response(
            200,
            content=body,
            headers={
                "ETag": etag,
                "Last-Modified": "Fri, 01 Nov 2024 06:05:00 GMT",
                "Content-Type": "application/json",
            },
        )

    def client(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self.handler))


@pytest.fixture
def fake_sec(submissions_aapl, facts_aapl, submissions_msft, facts_msft, tickers_payload):
    f = FakeSEC()
    f.add("https://data.sec.gov/submissions/CIK0000320193.json", submissions_aapl)
    f.add("https://data.sec.gov/api/xbrl/companyfacts/CIK0000320193.json", facts_aapl)
    f.add("https://data.sec.gov/submissions/CIK0000789019.json", submissions_msft)
    f.add("https://data.sec.gov/api/xbrl/companyfacts/CIK0000789019.json", facts_msft)
    f.add("https://www.sec.gov/files/company_tickers_exchange.json", tickers_payload)
    return f


@pytest.fixture
def sec_client(settings, fake_sec):
    from app.services.sec_client import SecClient

    return SecClient(settings, http=fake_sec.client(), sleep=lambda s: None)


@pytest.fixture
def app(settings, engine, sec_client):
    from app.api.dependencies import rate_limiter
    from app.main import create_app

    rate_limiter.reset()
    application = create_app(settings)
    application.state.sec_client_factory = lambda: sec_client
    return application


@pytest.fixture
def client(app):
    with TestClient(app) as c:
        yield c


@pytest.fixture
def api_key(db, settings):
    from app.services.api_keys import create_key_record

    key, raw = create_key_record(db, settings, "dev@example.com", "free", "test", actor="test")
    db.commit()
    return raw


@pytest.fixture
def auth(api_key):
    return {"X-API-Key": api_key}


@pytest.fixture
def ingested_aapl(db, sec_client):
    from app.services.ingestion import ingest_company

    return ingest_company(db, sec_client, "320193")
