from app.core.config import PLAN_LIMITS, Settings, plan_limits


def test_all_advertised_plans_exist_with_pricing_page_limits():
    s = Settings(
        sec_user_agent="x contact=a@b.test",
        api_key_pepper="p" * 20,
        webhook_signing_secret="w" * 20,
    )
    assert set(PLAN_LIMITS) == {"free", "builder", "team", "enterprise", "internal", "pilot"}
    assert plan_limits("pilot", s) == plan_limits("builder", s)  # legacy name keeps Builder limits
    assert all("max_active_watches" in p for p in PLAN_LIMITS.values())
    free, builder, team = plan_limits("free", s), plan_limits("builder", s), plan_limits("team", s)
    assert (free["rate_limit_per_minute"], free["monthly_request_quota"], free["max_watches"]) == (
        60,
        10_000,
        5,
    )
    assert (
        builder["rate_limit_per_minute"],
        builder["monthly_request_quota"],
        builder["max_watches"],
    ) == (300, 250_000, 50)
    assert (team["rate_limit_per_minute"], team["monthly_request_quota"], team["max_watches"]) == (
        1000,
        2_000_000,
        500,
    )
    assert all(p["max_export_rows"] <= s.max_export_rows for p in (free, builder, team))
    assert plan_limits("unknown-plan", s) == free
