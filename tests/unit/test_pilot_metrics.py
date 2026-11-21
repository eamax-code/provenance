"""The pilot's measures from docs/launch-plan.md."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.services import pilot_metrics


def test_measures_from_accounts_keys_and_usage(db, settings):
    from app.db.models import Account, ApiUsage
    from app.services.api_keys import create_key_record

    now = datetime(2026, 11, 20, 12, tzinfo=UTC)
    fast = Account(email="fast@acme-labs.dev", created_at=now - timedelta(days=2))
    idle = Account(email="idle@acme-labs.dev", created_at=now - timedelta(days=10))
    db.add_all([fast, idle])
    key, _ = create_key_record(db, settings, "fast@acme-labs.dev", "free", None, actor="t")
    create_key_record(db, settings, "idle@acme-labs.dev", "free", None, actor="t")
    for i in range(12):  # first call 4 minutes after sign-up, 12 calls on day one, one via MCP
        db.add(ApiUsage(api_key_id=key.id, request_id=f"r{i}", http_status=200,
                        route_template="/v1/companies/{cik}/facts" + (" (mcp)" if i == 0 else ""),
                        occurred_at=fast.created_at + timedelta(minutes=4 + i)))  # fmt: skip
    # test activity never counts: reserved test domains and internal keys
    db.add(Account(email="ui-review@example.com", created_at=now - timedelta(days=1)))
    test_key, _ = create_key_record(db, settings, "ui-review@example.invalid", "builder", None,
                                    actor="t")  # fmt: skip
    db.add(ApiUsage(api_key_id=test_key.id, request_id="t1", http_status=200,
                    route_template="/v1/companies/{cik}/facts (mcp)",
                    occurred_at=now - timedelta(hours=1)))  # fmt: skip
    db.commit()
    m = pilot_metrics.collect(db, now=now)
    assert m["accounts"] == 2 and m["accounts_new_7d"] == 1
    assert m["first_call_median_minutes"] == 4.0
    assert m["activation_pct"] == 50.0
    assert m["weekly_active_keys"] == 1 and m["mcp_share_pct"] == 100.0
    text = pilot_metrics.render(m)
    assert "first call median minutes: 4.0  (target under 10: met)" in text
    assert "activation pct: 50.0  (target 40%: met)" in text


def test_empty_database(db):
    m = pilot_metrics.collect(db, now=datetime(2026, 11, 20, tzinfo=UTC))
    assert m["accounts"] == 0 and m["activation_pct"] is None and m["mcp_share_pct"] is None
    assert "not yet" in pilot_metrics.render(m)
