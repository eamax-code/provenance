"""Plans: the one source of truth for prices, limits and plan features (launch plan G-01).

The API's limits (`plan_limits`), `/v1/public/plans`, the pricing section, the JSON-LD offers on
the home page and the /developers/ limits table are all built from PLANS
(`scripts/sync_plans.py` writes the static parts; a test fails if they drift).

Enforced today: rate limit, monthly quota, export rows, watches, event streams, chat questions
a day, forecasts and keys per account. `commercial_use` is a label until the terms say more.
Overage and agent credits launch with billing (G-02) and stay out of public output until then.
Prices approved by the owner on 2026-11-22 ("fine for now").
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass(frozen=True)
class Plan:
    name: str
    label: str
    price_usd_per_month: int | None  # None: priced per contract
    annual_price_usd_per_month: int | None  # effective monthly price when billed yearly
    price_display: str
    audience: str
    use: str
    commercial_use: bool
    rate_limit_per_minute: int
    monthly_request_quota: int
    max_export_rows: int
    max_watches: int  # distinct companies (or type watches) watched
    max_active_watches: int  # watch rows across destinations
    max_event_streams: int  # concurrent SSE connections
    chat_questions_per_day: int
    forecasts: bool
    max_keys: int
    support: str
    featured: bool = False
    public: bool = True  # shown on the pricing page and /v1/public/plans
    features: tuple[str, ...] = ()
    with_billing: dict = field(default_factory=dict)  # hidden until billing (G-02)


PLANS: dict[str, Plan] = {
    "free": Plan(
        "free",
        "Free",
        0,
        0,
        "$0",
        "Trying it out",
        "Personal, non-commercial",
        False,
        rate_limit_per_minute=60,
        monthly_request_quota=10_000,
        max_export_rows=100,
        max_watches=3,
        max_active_watches=3,
        max_event_streams=1,
        chat_questions_per_day=20,
        forecasts=False,
        max_keys=2,
        support="Docs",
        features=(
            "All metrics with citations",
            "Point in time (as_of)",
            "MCP server",
            "3 watches by webhook",
            "CSV export, 100 rows",
            "Attribution required",
        ),
    ),
    "analyst": Plan(
        "analyst",
        "Analyst",
        19,
        15,
        "$19",
        "Analysts, students and researchers",
        "Personal",
        False,
        rate_limit_per_minute=120,
        monthly_request_quota=50_000,
        max_export_rows=1000,
        max_watches=25,
        max_active_watches=50,
        max_event_streams=1,
        chat_questions_per_day=200,
        forecasts=True,
        max_keys=2,
        support="Email",
        features=(
            "Everything in Free",
            "Forecasts in chat",
            "25 watches by webhook",
            "CSV export, 1,000 rows",
            "200 chat questions a day",
        ),
    ),
    "builder": Plan(
        "builder",
        "Builder",
        79,
        65,
        "$79",
        "AI apps, fintech and dashboards",
        "Commercial display with attribution",
        True,
        rate_limit_per_minute=300,
        monthly_request_quota=500_000,
        max_export_rows=1000,
        max_watches=100,
        max_active_watches=200,
        max_event_streams=3,
        chat_questions_per_day=500,
        forecasts=True,
        max_keys=5,
        support="Email within two business days",
        featured=True,
        features=(
            "Commercial use in your product",
            "100 watches, webhooks and live stream",
            "500,000 requests a month",
            "5 keys",
        ),
        with_billing={"overage_usd_per_1000": 0.50},
    ),
    "team": Plan(
        "team",
        "Team",
        249,
        199,
        "$249",
        "Data teams and funds",
        "Commercial, internal and display",
        True,
        rate_limit_per_minute=1000,
        monthly_request_quota=3_000_000,
        max_export_rows=1000,
        max_watches=1000,
        max_active_watches=2000,
        max_event_streams=10,
        chat_questions_per_day=2000,
        forecasts=True,
        max_keys=20,
        support="Priority, one business day",
        features=(
            "Everything in Builder",
            "1,000 watches, 10 live streams",
            "3,000,000 requests a month",
            "20 keys",
            "Graph export",
        ),
        with_billing={"overage_usd_per_1000": 0.30},
    ),
    "enterprise": Plan(
        "enterprise",
        "Enterprise",
        None,
        None,
        "From $1,500",
        "Resellers and platforms",
        "Redistribution and resale by contract",
        True,
        rate_limit_per_minute=3000,
        monthly_request_quota=50_000_000,
        max_export_rows=1000,
        max_watches=5000,
        max_active_watches=10_000,
        max_event_streams=50,
        chat_questions_per_day=5000,
        forecasts=True,
        max_keys=100,
        support="SLA",
        features=(
            "Custom limits and terms",
            "Bulk snapshots after legal review",
            "SSO",
            "Annual contract",
        ),
    ),
    # Not sold: operator keys, and the first release's "pilot" keys, which keep Builder limits
    # until 2027-01-31 (then Builder at the founding price, or Free).
    "internal": Plan(
        "internal",
        "Internal",
        None,
        None,
        "-",
        "Operators",
        "Internal",
        True,
        rate_limit_per_minute=1000,
        monthly_request_quota=10_000_000,
        max_export_rows=1000,
        max_watches=5000,
        max_active_watches=10_000,
        max_event_streams=50,
        chat_questions_per_day=5000,
        forecasts=True,
        max_keys=100,
        support="-",
        public=False,
    ),
}
PLANS["pilot"] = Plan(**{**asdict(PLANS["builder"]), "name": "pilot", "label": "Pilot",
                         "public": False, "featured": False})  # fmt: skip
PILOT_UNTIL = "2027-01-31"

PUBLIC_PLAN_NAMES = tuple(n for n, p in PLANS.items() if p.public)
# Plans a visitor can ask for on the key request form (Enterprise is a conversation).
REQUESTABLE_PLANS = ("free", "analyst", "builder", "team", "enterprise")
# Ordering for "the best plan among an account's keys".
PLAN_RANK = ("free", "analyst", "builder", "pilot", "team", "enterprise", "internal")
LIMIT_FIELDS = (
    "rate_limit_per_minute", "monthly_request_quota", "max_export_rows", "max_watches",
    "max_active_watches", "max_event_streams", "chat_questions_per_day", "max_keys",
)  # fmt: skip


def limits_of(name: str) -> dict[str, int]:
    plan = PLANS.get(name, PLANS["free"])
    return {f: getattr(plan, f) for f in LIMIT_FIELDS}


def public_view(plan: Plan) -> dict:
    """What a visitor may see: everything except the billing-only parts."""
    d = asdict(plan)
    for hidden in ("with_billing", "public"):
        d.pop(hidden)
    d["features"] = list(plan.features)
    return d
