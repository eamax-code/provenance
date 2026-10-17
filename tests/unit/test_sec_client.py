import httpx
import pytest

from app.services.sec_client import SecClient, SecNotFound, SecUnavailable, submissions_url


def test_user_agent_is_required(settings):
    bad = settings.model_copy(update={"sec_user_agent": "nothing"})
    with pytest.raises(ValueError):
        SecClient(bad)


def test_fetch_uses_etag_cache_on_second_call(settings, fake_sec):
    client = SecClient(settings, http=fake_sec.client(), sleep=lambda s: None)
    first = client.fetch_submissions("320193")
    second = client.fetch_submissions("320193")
    assert first.from_cache is False and second.from_cache is True
    assert second.status_code == 304 and second.data == first.data
    assert second.payload_hash == first.payload_hash
    assert first.last_modified is not None and first.last_modified.tzinfo is not None


def test_retries_on_429_and_5xx_then_succeeds(settings, fake_sec):
    sleeps = []
    client = SecClient(settings, http=fake_sec.client(), sleep=sleeps.append)
    fake_sec.fail_statuses = [429, 503]
    resp = client.fetch_submissions("320193")
    assert resp.status_code == 200 and resp.retries == 2
    assert len(sleeps) == 2 and all(s >= 0 for s in sleeps)


def test_gives_up_after_max_retries(settings, fake_sec):
    client = SecClient(settings, http=fake_sec.client(), sleep=lambda s: None)
    fake_sec.fail_statuses = [500, 500, 500, 500]
    with pytest.raises(SecUnavailable):
        client.fetch_submissions("320193")
    # settings.sec_max_retries == 2 -> 3 attempts total
    assert len([c for c in fake_sec.calls if "CIK0000320193" in c]) == 3


def test_404_is_not_retried(settings, fake_sec):
    client = SecClient(settings, http=fake_sec.client(), sleep=lambda s: None)
    with pytest.raises(SecNotFound):
        client.fetch_submissions("999")
    assert fake_sec.calls.count(submissions_url("999")) == 1


def test_network_errors_are_retried(settings):
    attempts = {"n": 0}

    def handler(request):
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise httpx.ConnectError("boom", request=request)
        return httpx.Response(200, json={"cik": "1"})

    client = SecClient(
        settings, http=httpx.Client(transport=httpx.MockTransport(handler)), sleep=lambda s: None
    )
    assert client.get_json("https://data.sec.gov/x.json").data == {"cik": "1"}


def test_retry_after_header_is_respected(settings):
    assert (
        SecClient(
            settings,
            http=httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200))),
            sleep=lambda s: None,
        )._backoff(0, "7")
        == 7.0
    )


def test_rate_limiter_enforces_min_interval(settings):
    import time

    from app.services.sec_client import _IntervalLimiter

    limiter = _IntervalLimiter(0.05)
    start = time.monotonic()
    limiter.wait()
    limiter.wait()
    limiter.wait()
    assert time.monotonic() - start >= 0.09
