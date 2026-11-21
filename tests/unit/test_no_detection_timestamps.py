"""The owner's rule (2026-11-04): no source-side or detection timestamps in any response."""

from __future__ import annotations

import importlib
import inspect
import pkgutil
import re

from pydantic import BaseModel

import app.api
import app.schemas

BANNED = re.compile(r"detected_at|first_detected|source_updated|detected_since|cusip", re.I)


def _models():
    for pkg in (app.schemas, app.api):
        for mod in pkgutil.iter_modules(pkg.__path__):
            module = importlib.import_module(f"{pkg.__name__}.{mod.name}")
            for _, obj in inspect.getmembers(module, inspect.isclass):
                if issubclass(obj, BaseModel) and obj.__module__ == module.__name__:
                    yield obj


def test_no_response_model_has_a_detection_timestamp():
    found = [f"{m.__module__}.{m.__name__}.{f}" for m in _models() for f in m.model_fields
             if BANNED.search(f)]  # fmt: skip
    assert found == []


def test_openapi_has_no_detection_timestamp(client):
    text = client.get("/openapi.json").text
    assert not BANNED.search(text), BANNED.search(text).group(0)


def test_listing_event_dicts_have_no_detection_time(add_listings, client, auth, settings):
    settings.events_settle_seconds = 0
    add_listings(["AAA"])
    from datetime import UTC, datetime, timedelta

    since = (datetime.now(UTC) - timedelta(days=1)).isoformat().replace("+00:00", "Z")
    feed = client.get(f"/v1/events?types=listing&since={since}", headers=auth).json()
    assert feed["data"] and all(not BANNED.search(str(e)) for e in feed["data"])
    public = client.get("/v1/public/listings/events").text
    assert not BANNED.search(public)
    keyed = client.get("/v1/markets/events", headers=auth).text
    assert not BANNED.search(keyed)
    for path in (
        "/v1/stats",
        "/v1/public/plans",
        "/v1/public/ipos",
        "/v1/public/events",
        "/v1/public/insider-activity",
    ):  # dict responses, not models
        assert not BANNED.search(client.get(path, headers=auth).text), path
