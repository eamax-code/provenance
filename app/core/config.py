"""Application settings loaded from environment variables / .env.

All secrets come from the environment. Nothing here is logged in full.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_PLACEHOLDER_DOMAINS = ("@example.com", "@example.org", "@example.net", "replace-with")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore", case_sensitive=False
    )

    app_env: Literal["development", "test", "staging", "production"] = "development"
    app_name: str = "Provenance"
    app_version: str = "0.1.0"
    log_level: str = "INFO"
    log_json: bool = True

    database_url: str = "sqlite:///./dev.sqlite3"

    # SEC fair-access settings
    sec_user_agent: str = ""
    sec_min_request_interval_seconds: float = 0.25
    sec_timeout_seconds: float = 20.0
    sec_max_retries: int = 5
    sec_max_response_bytes: int = 50 * 1024 * 1024
    sec_cache_dir: str = ".sec_cache"
    sec_base_data_url: str = "https://data.sec.gov"
    sec_base_www_url: str = "https://www.sec.gov"
    sec_live_tests: bool = False

    ingestion_poll_interval_seconds: int = 300
    # Universe (bulk coverage) settings
    universe_refresh_interval_seconds: int = 6 * 3600
    universe_request_budget_per_run: int = 400
    universe_max_consecutive_failures: int = 10
    sec_filings_history_pages: int = 0
    freshness_stale_after_seconds: int = 24 * 3600
    on_demand_ingestion_enabled: bool = True

    # Security
    api_key_pepper: str = ""
    webhook_signing_secret: str = ""
    admin_token: str = ""

    # Limits
    max_export_rows: int = 1000
    default_rate_limit_per_minute: int = 60
    default_monthly_request_quota: int = 10_000

    # Webhooks
    webhook_timeout_seconds: float = 5.0
    webhook_max_attempts: int = 6
    webhook_retry_base_seconds: float = 30.0
    webhook_allow_private_destinations: bool = False

    # Email (optional)
    email_provider: Literal["none", "smtp"] = "none"
    email_from: str = ""
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_use_tls: bool = True

    usage_retention_days: int = 90
    delivery_retention_days: int = 90

    @field_validator("sec_user_agent")
    @classmethod
    def _validate_user_agent(cls, v: str) -> str:
        return v.strip()

    @property
    def email_configured(self) -> bool:
        return self.email_provider == "smtp" and bool(self.smtp_host and self.email_from)

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    def validate_for_runtime(self) -> list[str]:
        """Return a list of human-readable configuration problems (no secret values)."""
        problems: list[str] = []
        if not self.sec_user_agent or "contact=" not in self.sec_user_agent:
            problems.append("SEC_USER_AGENT must be set and include 'contact=<email>'")
        elif any(d in self.sec_user_agent.lower() for d in _PLACEHOLDER_DOMAINS):
            problems.append(
                "SEC_USER_AGENT contact address is a placeholder; use a monitored mailbox"
            )
        if not self.api_key_pepper or len(self.api_key_pepper) < 16:
            problems.append("API_KEY_PEPPER must be set to a random secret of at least 16 chars")
        if not self.webhook_signing_secret or len(self.webhook_signing_secret) < 16:
            problems.append(
                "WEBHOOK_SIGNING_SECRET must be set to a random secret of at least 16 chars"
            )
        if self.is_production and self.database_url.startswith("sqlite"):
            problems.append("SQLite is not supported in production; use PostgreSQL")
        if self.is_production and self.webhook_allow_private_destinations:
            problems.append("WEBHOOK_ALLOW_PRIVATE_DESTINATIONS must be false in production")
        return problems


PLAN_LIMITS: dict[str, dict[str, int]] = {
    # Advertised on the pricing page; keep in sync with site/index.html.
    # rate limit per minute, requests per calendar month, export rows per request, watched CIKs
    "free": {
        "rate_limit_per_minute": 60,
        "monthly_request_quota": 10_000,
        "max_export_rows": 1000,
        "max_watches": 5,
    },
    "builder": {
        "rate_limit_per_minute": 300,
        "monthly_request_quota": 250_000,
        "max_export_rows": 1000,
        "max_watches": 50,
    },
    "team": {
        "rate_limit_per_minute": 1000,
        "monthly_request_quota": 2_000_000,
        "max_export_rows": 1000,
        "max_watches": 500,
    },
    "enterprise": {
        "rate_limit_per_minute": 3000,
        "monthly_request_quota": 50_000_000,
        "max_export_rows": 1000,
        "max_watches": 5000,
    },
    "internal": {
        "rate_limit_per_minute": 1000,
        "monthly_request_quota": 10_000_000,
        "max_export_rows": 1000,
        "max_watches": 5000,
    },
}
PLAN_NAMES = tuple(PLAN_LIMITS)


def plan_limits(plan: str, settings: Settings) -> dict[str, int]:
    base = dict(PLAN_LIMITS.get(plan, PLAN_LIMITS["free"]))
    if plan == "free":
        base["rate_limit_per_minute"] = settings.default_rate_limit_per_minute
        base["monthly_request_quota"] = settings.default_monthly_request_quota
    base["max_export_rows"] = min(base["max_export_rows"], settings.max_export_rows)
    return base


@lru_cache
def get_settings() -> Settings:
    return Settings()


__all__ = ["Settings", "get_settings", "plan_limits", "PLAN_LIMITS", "PLAN_NAMES", "Field"]
