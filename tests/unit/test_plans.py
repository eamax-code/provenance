from app.core.config import PLAN_LIMITS, Settings, plan_limits
from app.core.plans import PLANS, PUBLIC_PLAN_NAMES, public_view


def _settings():
    return Settings(
        sec_user_agent="x contact=a@b.test", api_key_pepper="p" * 20,
        webhook_signing_secret="w" * 20,
    )  # fmt: skip


def test_limits_come_from_the_one_plan_table():
    s = _settings()
    assert set(PLAN_LIMITS) == set(PLANS) == {
        "free", "analyst", "builder", "team", "enterprise", "internal", "pilot"
    }  # fmt: skip
    assert PUBLIC_PLAN_NAMES == ("free", "analyst", "builder", "team", "enterprise")
    assert plan_limits("pilot", s) == plan_limits("builder", s)  # legacy keys keep Builder
    expected = {  # launch plan section 4, approved 2026-11-22
        "free": (60, 10_000, 3, 100, 20, 2),
        "analyst": (120, 50_000, 25, 1000, 200, 2),
        "builder": (300, 500_000, 100, 1000, 500, 5),
        "team": (1000, 3_000_000, 1000, 1000, 2000, 20),
    }
    for name, want in expected.items():
        lim = plan_limits(name, s)
        got = tuple(lim[k] for k in ("rate_limit_per_minute", "monthly_request_quota",
                                     "max_watches", "max_export_rows",
                                     "chat_questions_per_day", "max_keys"))  # fmt: skip
        assert got == want, name
    prices = {n: (PLANS[n].price_usd_per_month, PLANS[n].annual_price_usd_per_month)
              for n in PUBLIC_PLAN_NAMES}  # fmt: skip
    assert prices == {"free": (0, 0), "analyst": (19, 15), "builder": (79, 65),
                      "team": (249, 199), "enterprise": (None, None)}  # fmt: skip
    assert [n for n in PUBLIC_PLAN_NAMES if PLANS[n].featured] == ["builder"]
    assert [n for n in PUBLIC_PLAN_NAMES if PLANS[n].commercial_use] == [
        "builder", "team", "enterprise"
    ]  # fmt: skip
    assert not PLANS["free"].forecasts and PLANS["analyst"].forecasts
    assert plan_limits("unknown-plan", s) == plan_limits("free", s)


def test_billing_only_parts_never_reach_public_output():
    for name in PUBLIC_PLAN_NAMES:
        view = public_view(PLANS[name])
        assert "with_billing" not in view and "overage" not in str(view).lower()


def test_static_plan_copies_match_the_table():
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
    import sync_plans

    assert sync_plans.out_of_date() == [], "run: python scripts/sync_plans.py"
    assert '"Builder", "price": "79"' in sync_plans.offers()
