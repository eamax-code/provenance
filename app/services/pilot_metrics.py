"""The pilot's measures (docs/launch-plan.md), read from the database: accounts, time to the
first successful call, activation, weekly active keys, the share that use MCP, and data quality.
Demo-key traffic is not counted: it has no key and no account."""

from __future__ import annotations

import statistics
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import Account, ApiKey, ApiUsage, DataQualitySnapshot

ACTIVATION_CALLS = 10
ACTIVATION_WINDOW = timedelta(hours=24)


def _utc(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)


# Test and operator activity never counts: reserved test domains (RFC 2606) and internal keys.
TEST_DOMAINS = (".invalid", "@example.com", "@example.org", "@example.net", ".test")


def is_internal(email: str | None, plan: str | None = None) -> bool:
    e = (email or "").lower()
    return plan == "internal" or any(e.endswith(d) for d in TEST_DOMAINS)


def collect(db: Session, now: datetime | None = None) -> dict:
    now = now or datetime.now(UTC)
    week_ago = now - timedelta(days=7)
    accounts = [a for a in db.scalars(select(Account)) if not is_internal(a.email)]
    keys_by_email: dict[str, list] = {}
    internal: set = set()
    for key in db.scalars(select(ApiKey)):
        if is_internal(key.owner_email, key.plan):
            internal.add(key.id)
            continue
        keys_by_email.setdefault(key.owner_email.lower(), []).append(key.id)

    first_call_minutes: list[float] = []
    activated = 0
    for account in accounts:
        ids = keys_by_email.get(account.email, [])
        if not ids:
            continue
        created = _utc(account.created_at)
        first = db.scalar(
            select(func.min(ApiUsage.occurred_at)).where(
                ApiUsage.api_key_id.in_(ids),
                ApiUsage.http_status < 400,
                ApiUsage.occurred_at >= created,
            )
        )
        if first is not None:
            first_call_minutes.append((_utc(first) - created).total_seconds() / 60)
        calls = db.scalar(
            select(func.count(ApiUsage.id)).where(
                ApiUsage.api_key_id.in_(ids),
                ApiUsage.occurred_at >= created,
                ApiUsage.occurred_at < created + ACTIVATION_WINDOW,
            )
        )
        activated += int(calls >= ACTIVATION_CALLS)

    active_keys = (
        set(
            db.scalars(
                select(ApiUsage.api_key_id).where(ApiUsage.occurred_at >= week_ago).distinct()
            )
        )
        - internal
    )
    mcp_keys = (
        set(
            db.scalars(
                select(ApiUsage.api_key_id)
                .where(ApiUsage.occurred_at >= week_ago, ApiUsage.route_template.like("% (mcp)"))
                .distinct()
            )
        )
        - internal
    )
    snap = db.scalar(select(DataQualitySnapshot).order_by(DataQualitySnapshot.taken_at.desc()))
    ok_pct = None
    if snap is not None and snap.facts_total:
        ok_pct = round(100 * snap.facts_ok / snap.facts_total, 1)
    return {
        "as_of": now.isoformat(),
        "accounts": len(accounts),
        "accounts_new_7d": sum(1 for a in accounts if _utc(a.created_at) >= week_ago),
        "first_call_median_minutes": round(statistics.median(first_call_minutes), 1)
        if first_call_minutes
        else None,
        "activation_pct": round(100 * activated / len(accounts), 1) if accounts else None,
        "weekly_active_keys": len(active_keys),
        "mcp_share_pct": round(100 * len(mcp_keys) / len(active_keys), 1) if active_keys else None,
        "facts_ok_pct": ok_pct,
        "accept_to_detect_p50_seconds": snap.accept_to_detect_p50_s if snap else None,
    }


TARGETS = {
    "first_call_median_minutes": ("under 10", lambda v: v is not None and v < 10),
    "activation_pct": ("40%", lambda v: v is not None and v >= 40),
    "weekly_active_keys": ("25 by day 30", lambda v: v >= 25),
    "mcp_share_pct": ("30%", lambda v: v is not None and v >= 30),
    "facts_ok_pct": ("95%", lambda v: v is not None and v >= 95),
}


def render(m: dict) -> str:
    lines = [f"Pilot measures as of {m['as_of'][:16].replace('T', ' ')} UTC"]
    for name, value in m.items():
        if name == "as_of":
            continue
        target = TARGETS.get(name)
        mark = ""
        if target:
            mark = f"  (target {target[0]}: {'met' if target[1](value) else 'not yet'})"
        lines.append(f"  {name.replace('_', ' ')}: {'—' if value is None else value}{mark}")
    return "\n".join(lines)
